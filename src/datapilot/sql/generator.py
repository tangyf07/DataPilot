"""SQL generator: mock/rules offline or OpenAI-compatible API.

Dialects:
  - duckdb: date predicates with ``current_date - INTERVAL``
  - mysql / doris: portable SELECT (metric_id filter + ORDER BY); avoids DuckDB-only INTERVAL
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datapilot.intent import Intent
from datapilot.rag.base import RetrievedDoc


@dataclass
class SQLGeneration:
    sql: str
    model: str
    prompt: str
    mode: str


def _dialect(settings: Any) -> str:
    d = getattr(settings, "sql_dialect", None)
    if d:
        return str(d).lower()
    backend = getattr(settings, "effective_backend", None) or getattr(settings, "query_backend", "duckdb")
    if str(backend).lower() == "doris":
        return "mysql"
    return "duckdb"


def _date_predicate(time_hint: str | None, col: str = "dt", *, dialect: str = "duckdb") -> str:
    if dialect in ("mysql", "doris"):
        # Doris/MySQL-portable forms
        if time_hint == "yesterday":
            return f"{col} = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
        if time_hint == "today":
            return f"{col} = CURRENT_DATE()"
        if time_hint == "last_7_days":
            return f"{col} >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)"
        if time_hint == "last_14_days":
            return f"{col} >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)"
        return f"{col} = (SELECT max({col}) FROM {{table}})"
    # DuckDB
    if time_hint == "yesterday":
        return f"{col} = current_date - INTERVAL 1 DAY"
    if time_hint == "today":
        return f"{col} = current_date"
    if time_hint == "last_7_days":
        return f"{col} >= current_date - INTERVAL 7 DAY"
    if time_hint == "last_14_days":
        return f"{col} >= current_date - INTERVAL 14 DAY"
    return f"{col} = (SELECT max({col}) FROM {{table}})"


def _server_clause(server_id: int | None) -> str | None:
    if server_id is None:
        return None
    return f"server_id = {int(server_id)}"


def _portable_ads_sql(metric: str, server_id: int | None = None) -> str | None:
    """Preferred portable SQL for Doris ADS (G7) — no DuckDB INTERVAL."""
    sid = _server_clause(server_id)
    if metric == "dau":
        where = ["metric_id = 'ads_dau_di'"]
        if sid:
            where.append(sid)
        return (
            "SELECT dt, server_id, dau, metric_id FROM ads_dau_di WHERE "
            + " AND ".join(where)
            + " ORDER BY dt, server_id"
        )
    if metric in ("pay_rate", "pay_users"):
        where = ["metric_id = 'ads_pay_rate_di'"]
        if sid:
            where.append(sid)
        return (
            "SELECT dt, server_id, dau, pay_users, pay_rate, metric_id FROM ads_pay_rate_di WHERE "
            + " AND ".join(where)
            + " ORDER BY dt, server_id"
        )
    return None


def _mock_sql(
    intent: Intent,
    docs: list[RetrievedDoc],
    feedback: str | None = None,
    *,
    dialect: str = "duckdb",
) -> SQLGeneration:
    metric = intent.metric or "dau"
    time_hint = intent.time_hint or "latest"
    server_id = getattr(intent, "server_id", None)

    prompt = (
        f"[mock] intent={intent.name} metric={metric} time={time_hint} "
        f"server_id={server_id} dialect={dialect} docs={[d.doc_id for d in docs]}"
    )
    if feedback:
        prompt += f"\n[retry_feedback] {feedback}"

    # G7 / Doris: always use portable ADS SQL for DAU + pay_rate
    if dialect in ("mysql", "doris"):
        portable = _portable_ads_sql(metric, server_id)
        if portable:
            mode = "mock_retry" if feedback else "mock_doris"
            return SQLGeneration(sql=portable, model="mock-rules-v1", prompt=prompt, mode=mode)
        # other metrics: still avoid DuckDB INTERVAL
        pass

    sid = _server_clause(server_id)

    if metric == "dau":
        # Prefer portable form even on DuckDB so seed + Doris stay aligned
        if dialect in ("mysql", "doris") or time_hint in ("latest", None):
            portable = _portable_ads_sql("dau", server_id)
            if portable and dialect in ("mysql", "doris"):
                sql = portable
            else:
                table = "ads_dau_di"
                pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
                where = [pred]
                if sid:
                    where.append(sid)
                sql = (
                    f"SELECT dt, server_id, dau, metric_id FROM {table} WHERE "
                    + " AND ".join(where)
                    + " ORDER BY dt, server_id"
                )
        else:
            table = "ads_dau_di"
            pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
            where = [pred]
            if sid:
                where.append(sid)
            sql = (
                f"SELECT dt, server_id, dau, metric_id FROM {table} WHERE "
                + " AND ".join(where)
                + " ORDER BY dt, server_id"
            )
    elif metric == "retention":
        table = "ads_retention_nd"
        pred = _date_predicate(time_hint, col="cohort_dt", dialect=dialect).format(table=table)
        where = [pred, "n_days IN (1, 3, 7)"]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT cohort_dt, server_id, n_days, cohort_size, retained_cnt, "
            f"retention_rate, metric_id FROM {table} WHERE "
            + " AND ".join(where)
            + " ORDER BY cohort_dt, server_id, n_days"
        )
    elif metric in ("arpu", "revenue"):
        table = "ads_arpu_di"
        pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, dau, revenue_cny, arpu_cny, metric_id FROM {table} WHERE "
            + " AND ".join(where)
            + " ORDER BY dt, server_id"
        )
    elif metric in ("pay_rate", "pay_users"):
        if dialect in ("mysql", "doris"):
            sql = _portable_ads_sql(metric, server_id) or ""
        else:
            table = "ads_pay_rate_di"
            pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
            where = [pred]
            if sid:
                where.append(sid)
            sql = (
                f"SELECT dt, server_id, dau, pay_users, pay_rate, metric_id FROM {table} WHERE "
                + " AND ".join(where)
                + " ORDER BY dt, server_id"
            )
    elif metric == "online_duration":
        table = "ads_online_duration_di"
        pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, total_online_sec, players, avg_online_sec, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id"
        )
    elif metric == "dungeon_clear":
        table = "ads_dungeon_clear_rate_di"
        pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, dungeon_id, enter_cnt, clear_cnt, clear_rate, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id, dungeon_id"
        )
    elif metric == "churn":
        table = "ads_churn_di"
        pred = _date_predicate(time_hint, dialect=dialect).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, active_7d_users, churn_risk_users, churn_risk_rate, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id"
        )
    else:
        if dialect in ("mysql", "doris"):
            sql = (
                "SELECT dt, server_id, dau, metric_id FROM ads_dau_di "
                "WHERE metric_id = 'ads_dau_di' ORDER BY dt, server_id"
            )
        else:
            sql = (
                "SELECT dt, server_id, dau, metric_id FROM ads_dau_di "
                "WHERE dt = (SELECT max(dt) FROM ads_dau_di) ORDER BY dt, server_id"
            )

    sql = sql.strip().rstrip(";").split(";")[0].strip()
    mode = "mock_retry" if feedback else ("mock_doris" if dialect in ("mysql", "doris") else "mock")
    return SQLGeneration(sql=sql, model="mock-rules-v1", prompt=prompt, mode=mode)


def _openai_sql(
    intent: Intent,
    docs: list[RetrievedDoc],
    settings: Any,
    feedback: str | None = None,
) -> SQLGeneration:
    dialect = _dialect(settings)
    dialect_hint = (
        "Doris/MySQL (GameStream ADS). Prefer unqualified table names with database=ads. "
        "Use DATE_SUB(CURRENT_DATE(), INTERVAL n DAY) or filter by metric_id; avoid DuckDB INTERVAL."
        if dialect in ("mysql", "doris")
        else "DuckDB over GameStream ADS tables."
    )
    schema_blob = "\n\n".join(f"### {d.title}\n{d.content}" for d in docs)
    prompt = (
        f"You are a SQL generator for {dialect_hint}\n"
        "(ads_dau_di, ads_retention_nd, ads_arpu_di, ads_pay_rate_di, ...).\n"
        "Always include metric_id when selecting. No platform column. Use server_id.\n"
        "Return ONLY one SELECT statement. No DDL/DML.\n\n"
        f"Schema docs:\n{schema_blob}\n\n"
        f"Intent: {intent}\n"
        f"Question: {intent.raw}\n"
    )
    if feedback:
        prompt += (
            f"\nPrevious attempt failed. Feedback:\n{feedback}\n"
            "Regenerate a single safer SELECT only.\n"
        )
    try:
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        system = (
            "Output a single MySQL/Doris SELECT only."
            if dialect in ("mysql", "doris")
            else "Output a single DuckDB SELECT only."
        )
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(l for l in lines if not l.startswith("```"))
        return SQLGeneration(
            sql=text.strip().rstrip(";").split(";")[0].strip(),
            model=settings.openai_model,
            prompt=prompt,
            mode="openai_retry" if feedback else "openai",
        )
    except Exception as exc:  # noqa: BLE001
        fallback = _mock_sql(
            intent, docs, feedback=feedback or f"openai_error: {exc}", dialect=dialect
        )
        fallback.prompt = prompt + f"\n[openai_error->mock] {exc}"
        fallback.mode = "mock_fallback"
        return fallback


def generate_sql(
    intent: Intent,
    docs: list[RetrievedDoc],
    settings: Any,
    feedback: str | None = None,
) -> SQLGeneration:
    """Generate SQL. On feedback (gate/query failure), regenerate safer SELECT (max 1 retry upstream)."""
    dialect = _dialect(settings)
    if getattr(settings, "llm_mode", "mock") == "openai" and getattr(settings, "openai_api_key", None):
        if feedback:
            return _mock_sql(intent, docs, feedback=feedback, dialect=dialect)
        return _openai_sql(intent, docs, settings, feedback=None)
    return _mock_sql(intent, docs, feedback=feedback, dialect=dialect)
