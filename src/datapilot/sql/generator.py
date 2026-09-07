"""SQL generator: mock/rules offline or OpenAI-compatible API.

Business calendar timezone: **Asia/Shanghai** (UTC+8). Date predicates
(``today`` / ``yesterday`` / ``last_7_days``) use the operator's ``CURRENT_DATE`` /
``current_date``; run DataPilot in Asia/Shanghai (or align the warehouse clock)
so "今天" matches the Shanghai calendar day.

Dialects:
  - duckdb: date predicates with ``current_date - INTERVAL``
  - mysql / doris: portable SELECT with ``DATE_SUB`` predicates from time_hint

``last_7_days`` is the inclusive window **[today-6d, today]** (7 calendar days
including today). ``yesterday`` = today-1; ``today`` = today.
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
    """Build a date filter. Business TZ: Asia/Shanghai (see module docstring).

    last_7_days → inclusive [today-6d, today] (7 calendar days including today).
    """
    if dialect in ("mysql", "doris"):
        if time_hint == "yesterday":
            return f"{col} = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)"
        if time_hint == "today":
            return f"{col} = CURRENT_DATE()"
        if time_hint == "last_7_days":
            # inclusive [today-6, today] = 7 days
            return (
                f"{col} >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 DAY) "
                f"AND {col} <= CURRENT_DATE()"
            )
        if time_hint == "last_14_days":
            return (
                f"{col} >= DATE_SUB(CURRENT_DATE(), INTERVAL 13 DAY) "
                f"AND {col} <= CURRENT_DATE()"
            )
        return f"{col} = (SELECT max({col}) FROM {{table}})"
    # DuckDB
    if time_hint == "yesterday":
        return f"{col} = current_date - INTERVAL 1 DAY"
    if time_hint == "today":
        return f"{col} = current_date"
    if time_hint == "last_7_days":
        return f"{col} >= current_date - INTERVAL 6 DAY AND {col} <= current_date"
    if time_hint == "last_14_days":
        return f"{col} >= current_date - INTERVAL 13 DAY AND {col} <= current_date"
    return f"{col} = (SELECT max({col}) FROM {{table}})"


def _server_clause(server_id: int | None) -> str | None:
    if server_id is None:
        return None
    return f"server_id = {int(server_id)}"


def _portable_ads_sql(
    metric: str,
    server_id: int | None = None,
    *,
    time_hint: str | None = None,
    dialect: str = "mysql",
) -> str | None:
    """Preferred portable SQL for Doris ADS (G7) with time_hint date predicates."""
    sid = _server_clause(server_id)
    th = time_hint or "latest"
    if metric == "dau":
        table = "ads_dau_di"
        pred = _date_predicate(th, dialect=dialect).format(table=table)
        where = [pred, "metric_id = 'ads_dau_di'"]
        if sid:
            where.append(sid)
        return (
            f"SELECT dt, server_id, dau, metric_id FROM {table} WHERE "
            + " AND ".join(where)
            + " ORDER BY dt, server_id"
        )
    if metric in ("pay_rate", "pay_users"):
        table = "ads_pay_rate_di"
        pred = _date_predicate(th, dialect=dialect).format(table=table)
        where = [pred, "metric_id = 'ads_pay_rate_di'"]
        if sid:
            where.append(sid)
        return (
            f"SELECT dt, server_id, dau, pay_users, pay_rate, metric_id FROM {table} WHERE "
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
        f"server_id={server_id} dialect={dialect} tz=Asia/Shanghai "
        f"docs={[d.doc_id for d in docs]}"
    )
    if feedback:
        prompt += f"\n[retry_feedback] {feedback}"

    # G7 / Doris: portable ADS SQL with time predicates for DAU + pay_rate
    if dialect in ("mysql", "doris"):
        portable = _portable_ads_sql(
            metric, server_id, time_hint=time_hint, dialect="mysql"
        )
        if portable:
            mode = "mock_retry" if feedback else "mock_doris"
            return SQLGeneration(sql=portable, model="mock-rules-v1", prompt=prompt, mode=mode)

    sid = _server_clause(server_id)

    if metric == "dau":
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
                "WHERE dt = (SELECT max(dt) FROM ads_dau_di) AND metric_id = 'ads_dau_di' "
                "ORDER BY dt, server_id"
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
        "Use DATE_SUB(CURRENT_DATE(), INTERVAL n DAY); last_7_days = inclusive [today-6, today]. "
        "Business TZ Asia/Shanghai. Avoid DuckDB INTERVAL."
        if dialect in ("mysql", "doris")
        else "DuckDB over GameStream ADS tables. Business TZ Asia/Shanghai. "
        "last_7_days = inclusive [today-6, today]."
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
