"""Orchestrates the ChatBI agent loop with SQLGuard gate + one feedback retry."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from datapilot.config import Settings, get_settings
from datapilot.guard.base import GateResult, build_guard_client
from datapilot.intent import Intent, recognize_intent
from datapilot.observe.tracer import Tracer
from datapilot.query.engine import DuckDBEngine, QueryResult
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
        }


class Pipeline:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.retriever = MockGameStreamRetriever()
        self.guard = build_guard_client(self.settings.guard_mode)
        self.engine = DuckDBEngine(self.settings.db_path, auto_seed=True)
        self.tracer = Tracer(self.settings.trace_dir)

    def run(self, question: str) -> PipelineResult:
        run = self.tracer.begin(question)

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
            )

            # 4 SQLGuard BEFORE query
            step = run.start_step(f"sqlguard{suffix}")
            gate = self.guard.check(sql_gen.sql)
            run.gate = {
                "allowed": gate.allowed,
                "action": gate.action,
                "rule_id": gate.rule_id,
                "reason": gate.reason,
                "risk": gate.risk,
                "attempt": attempts,
            }
            step.finish(**run.gate)

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
                )

            # 5 Query (DuckDB, seeded)
            step = run.start_step(f"query{suffix}")
            try:
                qres = self.engine.execute(sql_gen.sql)
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
                )

            # 6 Validate
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
        )


def run_question(question: str, settings: Settings | None = None) -> PipelineResult:
    return Pipeline(settings=settings).run(question)
