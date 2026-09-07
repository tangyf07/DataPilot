"""Orchestrates the ChatBI agent loop with SQLGuard gate + one feedback retry.

G7 path (Doris): generate SQL → SQLGuard block_or_execute(execute=True, database=Doris URL)
→ map rows to QueryResult; fallback check + pymysql if execute cannot talk Doris.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from datapilot.config import Settings, get_settings
from datapilot.guard.base import GateResult, build_guard_client
from datapilot.intent import Intent, recognize_intent
from datapilot.observe.tracer import Tracer
from datapilot.query.engine import (
    DorisEngine,
    
    QueryResult,
    build_engine,
    query_result_from_gate_rows,
)
from datapilot.rag.base import RetrievedDoc
from datapilot.rag.mock_gamestream import MockGameStreamRetriever
from datapilot.report.conclude import Report, build_report
from datapilot.sql.generator import SQLGeneration, generate_sql
from datapilot.sql.validator import ValidationResult, validate_result

# 1 initial attempt + 1 feedback retry
MAX_ATTEMPTS = 2


@dataclass
class PipelineResult:
    question: str
    intent: Intent
    docs: list[RetrievedDoc]
    sql_gen: SQLGeneration | None
    gate: GateResult | None
    query: QueryResult | None
    validation: ValidationResult | None
    report: Report | None
    trace_path: str
    blocked: bool = False
    error: str | None = None
    retries: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 1
    query_backend: str = "duckdb"
    query_path: str | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": asdict(self.intent),
            "docs": [{"id": d.doc_id, "title": d.title, "score": d.score} for d in self.docs],
            "sql": self.sql_gen.sql if self.sql_gen else None,
            "model": self.sql_gen.model if self.sql_gen else None,
            "gate": {
                "allowed": self.gate.allowed,
                "action": self.gate.action,
                "reason": self.gate.reason,
                "rule_id": self.gate.rule_id,
                "datapilot": self.gate.datapilot,
                "risk_score": self.gate.risk_score,
                "executed": self.gate.executed,
                "rowcount": self.gate.rowcount,
            }
            if self.gate
            else None,
            "row_count": self.validation.row_count if self.validation else 0,
            "conclusion": self.report.conclusion if self.report else None,
            "trace_path": self.trace_path,
            "blocked": self.blocked,
            "error": self.error,
            "retries": self.retries,
            "attempts": self.attempts,
            "query_backend": self.query_backend,
            "query_path": self.query_path,
        }


class Pipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.backend = self.settings.effective_backend
        self.retriever = MockGameStreamRetriever()
        # For Doris: pass database_url into WriteGate so execute hits MySQL/Doris
        database_url = self.settings.doris_url if self.backend == "doris" else None
        self.guard = build_guard_client(
            self.settings.guard_mode,
            guard_url=self.settings.guard_url,
            catalog_path=self.settings.guard_catalog,
            policy_path=self.settings.guard_policy,
            db_path=None if self.backend == "doris" else self.settings.db_path,
            database_url=database_url,
        )
        self.engine = build_engine(
            self.backend,
            db_path=self.settings.db_path,
            doris_url=self.settings.doris_url,
            auto_seed=True,
        )
        self.tracer = Tracer(self.settings.trace_dir)

    def _execute_doris_via_guard(self, sql: str) -> tuple[GateResult, QueryResult | None, str]:
        """True G7 path: SQLGuard execute against Doris; fallback check + pymysql.

        Returns (gate, query_or_none, path_label).
        """
        # Prefer execute=True through WriteGate (database=DATAPILOT_DORIS_URL)
        if hasattr(self.guard, "execute"):
            try:
                gate = self.guard.execute(sql)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                # Fall back to check-only then pymysql
                gate = self.guard.check(sql)
                if not gate.allowed:
                    return gate, None, "sqlguard_execute_failed"
                if isinstance(self.engine, DorisEngine):
                    qres = self.engine.execute(sql)
                    qres.path = "sqlguard_check_then_pymysql"
                    if isinstance(gate.raw, dict):
                        gate.raw = {
                            **gate.raw,
                            "execute_error": str(exc),
                            "fallback": "sqlguard_check_then_pymysql",
                        }
                    return gate, qres, "sqlguard_check_then_pymysql"
                raise

            if not gate.allowed:
                return gate, None, "sqlguard_execute"

            if gate.executed and gate.rows is not None:
                qres = query_result_from_gate_rows(
                    sql,
                    gate.rows,
                    columns=gate.columns,
                    path="sqlguard_execute",
                )
                return gate, qres, "sqlguard_execute"

            # EXECUTE allowed but WriteGate could not materialize rows (e.g. no pymysql)
            # → still gated: check already passed; run SELECT via DorisEngine
            if isinstance(self.engine, DorisEngine):
                qres = self.engine.execute(sql)
                qres.path = "sqlguard_check_then_pymysql"
                if isinstance(gate.raw, dict):
                    gate.raw = {
                        **gate.raw,
                        "fallback": "sqlguard_check_then_pymysql",
                        "note": "gate ALLOW but rows not materialized by WriteGate",
                    }
                return gate, qres, "sqlguard_check_then_pymysql"

            return gate, None, "sqlguard_execute"

        # Mock / check-only client
        gate = self.guard.check(sql)
        if not gate.allowed:
            return gate, None, "sqlguard_check"
        qres = self.engine.execute(sql)
        if isinstance(qres, QueryResult):
            qres.path = "sqlguard_check_then_engine"
        return gate, qres, "sqlguard_check_then_engine"

    def run(self, question: str) -> PipelineResult:
        run = self.tracer.begin(question)
        run.meta["query_backend"] = self.backend
        if self.settings.doris_url:
            run.meta["doris_url_set"] = True

        # 1 Intent
        step = run.start_step("intent")
        intent = recognize_intent(question)
        step.finish(intent=asdict(intent))

        # 2 RAG (SchemaRetriever / mock GameStream)
        step = run.start_step("rag")
        docs = self.retriever.retrieve(question, intent_name=intent.name, top_k=3)
        step.finish(docs=[{"id": d.doc_id, "score": d.score} for d in docs])

        feedback: str | None = None
        retries: list[dict[str, Any]] = []
        sql_gen: SQLGeneration | None = None
        gate: GateResult | None = None
        qres: QueryResult | None = None
        validation: ValidationResult | None = None
        query_path: str | None = None
        attempts = 0

        while attempts < MAX_ATTEMPTS:
            attempts += 1
            suffix = "" if attempts == 1 else "_retry"

            # 3 SQL generate (with optional gate/query feedback)
            step = run.start_step(f"sql_generate{suffix}")
            sql_gen = generate_sql(intent, docs, self.settings, feedback=feedback)
            run.model = sql_gen.model
            run.prompt = sql_gen.prompt
            run.sql = sql_gen.sql
            step.finish(
                sql=sql_gen.sql,
                model=sql_gen.model,
                mode=sql_gen.mode,
                attempt=attempts,
                feedback=feedback,
                dialect=self.settings.sql_dialect,
            )

            if self.backend == "doris":
                # 4+5 G7: SQLGuard execute (or check + pymysql) against Doris ADS
                step = run.start_step(f"sqlguard{suffix}")
                try:
                    gate, qres, query_path = self._execute_doris_via_guard(sql_gen.sql)
                except Exception as exc:  # noqa: BLE001
                    step.finish(error=str(exc))
                    retries.append(
                        {
                            "attempt": attempts,
                            "stage": "query",
                            "reason": str(exc),
                            "sql": sql_gen.sql,
                        }
                    )
                    run.meta["retries"] = retries
                    if attempts < MAX_ATTEMPTS:
                        feedback = f"Doris query failed: {exc}. Regenerate portable MySQL SELECT for ADS."
                        continue
                    run.meta["attempts"] = attempts
                    path = self.tracer.save(run)
                    return PipelineResult(
                        question=question,
                        intent=intent,
                        docs=docs,
                        sql_gen=sql_gen,
                        gate=gate,
                        query=None,
                        validation=None,
                        report=Report(
                            conclusion=f"查询失败（已重试）：{exc}",
                            table_text="(error)",
                            chart_path=None,
                        ),
                        trace_path=str(path),
                        error=str(exc),
                        retries=retries,
                        attempts=attempts,
                        query_backend=self.backend,
                        query_path=query_path,
                    )

                run.gate = {
                    "allowed": gate.allowed,
                    "action": gate.action,
                    "rule_id": gate.rule_id,
                    "reason": gate.reason,
                    "risk": gate.risk,
                    "datapilot": gate.datapilot,
                    "risk_score": gate.risk_score,
                    "latency_ms": gate.latency_ms,
                    "executed": gate.executed,
                    "rowcount": gate.rowcount,
                    "attempt": attempts,
                    "query_path": query_path,
                }
                step.finish(**run.gate)
                run.meta["query_path"] = query_path

                if not gate.allowed:
                    retries.append(
                        {
                            "attempt": attempts,
                            "stage": "gate",
                            "action": gate.action,
                            "reason": gate.reason,
                            "sql": sql_gen.sql,
                        }
                    )
                    run.meta["retries"] = retries
                    if attempts < MAX_ATTEMPTS:
                        feedback = (
                            f"SQLGuard {gate.action} ({gate.rule_id}): {gate.reason}. "
                            "Regenerate a single safe SELECT only (no DDL/DML/multi-statement)."
                        )
                        continue

                    report = Report(
                        conclusion=f"SQL 未通过 SQLGuard（已重试）：{gate.action} — {gate.reason}",
                        table_text="(blocked)",
                        chart_path=None,
                    )
                    run.meta["attempts"] = attempts
                    path = self.tracer.save(run)
                    return PipelineResult(
                        question=question,
                        intent=intent,
                        docs=docs,
                        sql_gen=sql_gen,
                        gate=gate,
                        query=None,
                        validation=None,
                        report=report,
                        trace_path=str(path),
                        blocked=True,
                        retries=retries,
                        attempts=attempts,
                        query_backend=self.backend,
                        query_path=query_path,
                    )

                # query step already done via guard
                step = run.start_step(f"query{suffix}")
                if qres is None:
                    step.finish(error="no rows from guard/engine")
                    retries.append(
                        {
                            "attempt": attempts,
                            "stage": "query",
                            "reason": "no rows from guard/engine",
                            "sql": sql_gen.sql,
                        }
                    )
                    run.meta["retries"] = retries
                    if attempts < MAX_ATTEMPTS:
                        feedback = "Query returned no result. Use portable SELECT on ads_dau_di / ads_pay_rate_di."
                        continue
                    run.meta["attempts"] = attempts
                    path = self.tracer.save(run)
                    return PipelineResult(
                        question=question,
                        intent=intent,
                        docs=docs,
                        sql_gen=sql_gen,
                        gate=gate,
                        query=None,
                        validation=None,
                        report=Report(
                            conclusion="查询失败（已重试）：无 result",
                            table_text="(error)",
                            chart_path=None,
                        ),
                        trace_path=str(path),
                        error="no rows from guard/engine",
                        retries=retries,
                        attempts=attempts,
                        query_backend=self.backend,
                        query_path=query_path,
                    )
                step.finish(
                    row_count=len(qres.rows),
                    columns=qres.columns,
                    backend=qres.backend,
                    path=qres.path,
                )

            else:
                # DuckDB path (offline): check then engine.execute
                step = run.start_step(f"sqlguard{suffix}")
                gate = self.guard.check(sql_gen.sql)
                run.gate = {
                    "allowed": gate.allowed,
                    "action": gate.action,
                    "rule_id": gate.rule_id,
                    "reason": gate.reason,
                    "risk": gate.risk,
                    "datapilot": gate.datapilot,
                    "risk_score": gate.risk_score,
                    "latency_ms": gate.latency_ms,
                    "attempt": attempts,
                }
                step.finish(**run.gate)
                query_path = "duckdb_direct"

                if not gate.allowed:
                    retries.append(
                        {
                            "attempt": attempts,
                            "stage": "gate",
                            "action": gate.action,
                            "reason": gate.reason,
                            "sql": sql_gen.sql,
                        }
                    )
                    run.meta["retries"] = retries
                    if attempts < MAX_ATTEMPTS:
                        feedback = (
                            f"SQLGuard {gate.action} ({gate.rule_id}): {gate.reason}. "
                            "Regenerate a single safe SELECT only (no DDL/DML/multi-statement)."
                        )
                        continue

                    report = Report(
                        conclusion=f"SQL 未通过 SQLGuard（已重试）：{gate.action} — {gate.reason}",
                        table_text="(blocked)",
                        chart_path=None,
                    )
                    run.meta["attempts"] = attempts
                    path = self.tracer.save(run)
                    return PipelineResult(
                        question=question,
                        intent=intent,
                        docs=docs,
                        sql_gen=sql_gen,
                        gate=gate,
                        query=None,
                        validation=None,
                        report=report,
                        trace_path=str(path),
                        blocked=True,
                        retries=retries,
                        attempts=attempts,
                        query_backend=self.backend,
                        query_path=query_path,
                    )

                step = run.start_step(f"query{suffix}")
                try:
                    qres = self.engine.execute(sql_gen.sql)
                    query_path = qres.path if isinstance(qres, QueryResult) else "duckdb_direct"
                    step.finish(row_count=len(qres.rows), columns=qres.columns)
                except Exception as exc:  # noqa: BLE001
                    step.finish(error=str(exc))
                    retries.append(
                        {
                            "attempt": attempts,
                            "stage": "query",
                            "reason": str(exc),
                            "sql": sql_gen.sql,
                        }
                    )
                    run.meta["retries"] = retries
                    if attempts < MAX_ATTEMPTS:
                        feedback = f"Query failed: {exc}. Fix DuckDB SELECT for ADS tables."
                        continue
                    run.meta["attempts"] = attempts
                    path = self.tracer.save(run)
                    return PipelineResult(
                        question=question,
                        intent=intent,
                        docs=docs,
                        sql_gen=sql_gen,
                        gate=gate,
                        query=None,
                        validation=None,
                        report=Report(
                            conclusion=f"查询失败（已重试）：{exc}",
                            table_text="(error)",
                            chart_path=None,
                        ),
                        trace_path=str(path),
                        error=str(exc),
                        retries=retries,
                        attempts=attempts,
                        query_backend=self.backend,
                        query_path=query_path,
                    )

            # 6 Validate
            assert qres is not None
            step = run.start_step(f"validate{suffix}")
            validation = validate_result(qres.columns, qres.rows)
            step.finish(ok=validation.ok, issues=validation.issues, row_count=validation.row_count)

            if not validation.ok and attempts < MAX_ATTEMPTS:
                retries.append(
                    {
                        "attempt": attempts,
                        "stage": "validate",
                        "reason": "; ".join(validation.issues) or "validation failed",
                        "sql": sql_gen.sql,
                    }
                )
                run.meta["retries"] = retries
                feedback = (
                    f"Validation issues: {validation.issues}. "
                    "Regenerate a simpler SELECT that returns rows."
                )
                continue

            break

        assert sql_gen is not None and gate is not None and qres is not None and validation is not None

        # 7 Conclude
        step = run.start_step("conclude")
        report = build_report(
            intent,
            qres.columns,
            qres.rows,
            validation.ok,
            chart_dir=self.settings.project_root / "traces",
        )
        step.finish(conclusion=report.conclusion, chart=report.chart_path)
        run.meta["retries"] = retries
        run.meta["attempts"] = attempts
        run.meta["query_path"] = query_path

        path = self.tracer.save(run)
        return PipelineResult(
            question=question,
            intent=intent,
            docs=docs,
            sql_gen=sql_gen,
            gate=gate,
            query=qres,
            validation=validation,
            report=report,
            trace_path=str(path),
            retries=retries,
            attempts=attempts,
            query_backend=self.backend,
            query_path=query_path,
        )


def run_question(question: str, settings: Settings | None = None) -> PipelineResult:
    return Pipeline(settings=settings).run(question)
