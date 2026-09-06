"""SQL generator: mock/rules offline or OpenAI-compatible API."""

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


def _date_predicate(time_hint: str | None, col: str = "dt") -> str:
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


def _mock_sql(intent: Intent, docs: list[RetrievedDoc], feedback: str | None = None) -> SQLGeneration:
    metric = intent.metric or "dau"
    time_hint = intent.time_hint or "latest"
    server_id = getattr(intent, "server_id", None)

    prompt = (
        f"[mock] intent={intent.name} metric={metric} time={time_hint} "
        f"server_id={server_id} docs={[d.doc_id for d in docs]}"
    )
    if feedback:
        prompt += f"\n[retry_feedback] {feedback}"

    sid = _server_clause(server_id)

    if metric == "dau":
        table = "ads_dau_di"
        pred = _date_predicate(time_hint).format(table=table)
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
        pred = _date_predicate(time_hint, col="cohort_dt").format(table=table)
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
        pred = _date_predicate(time_hint).format(table=table)
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
        pred = _date_predicate(time_hint).format(table=table)
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
        pred = _date_predicate(time_hint).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, total_online_sec, players, avg_online_sec, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id"
        )
    elif metric == "dungeon_clear":
        table = "ads_dungeon_clear_rate_di"
        pred = _date_predicate(time_hint).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, dungeon_id, enter_cnt, clear_cnt, clear_rate, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id, dungeon_id"
        )
    elif metric == "churn":
        table = "ads_churn_di"
        pred = _date_predicate(time_hint).format(table=table)
        where = [pred]
        if sid:
            where.append(sid)
        sql = (
            f"SELECT dt, server_id, active_7d_users, churn_risk_users, churn_risk_rate, metric_id "
            f"FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt, server_id"
        )
    else:
        sql = (
            "SELECT dt, server_id, dau, metric_id FROM ads_dau_di "
            "WHERE dt = (SELECT max(dt) FROM ads_dau_di) ORDER BY dt, server_id"
        )

    sql = sql.strip().rstrip(";").split(";")[0].strip()
    mode = "mock_retry" if feedback else "mock"
    return SQLGeneration(sql=sql, model="mock-rules-v1", prompt=prompt, mode=mode)


def _openai_sql(
    intent: Intent,
    docs: list[RetrievedDoc],
    settings: Any,
    feedback: str | None = None,
) -> SQLGeneration:
    schema_blob = "\n\n".join(f"### {d.title}\n{d.content}" for d in docs)
    prompt = (
        "You are a SQL generator for DuckDB over GameStream ADS tables "
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
        resp = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "Output a single DuckDB SELECT only."},
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
        fallback = _mock_sql(intent, docs, feedback=feedback or f"openai_error: {exc}")
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
    if getattr(settings, "llm_mode", "mock") == "openai" and getattr(settings, "openai_api_key", None):
        if feedback:
            return _mock_sql(intent, docs, feedback=feedback)
        return _openai_sql(intent, docs, settings, feedback=None)
    return _mock_sql(intent, docs, feedback=feedback)
