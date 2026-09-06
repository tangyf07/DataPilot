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


def _mock_sql(intent: Intent, docs: list[RetrievedDoc], feedback: str | None = None) -> SQLGeneration:
    metric = intent.metric or "dau"
    time_hint = intent.time_hint or "latest"
    platform = intent.platform

    prompt = (
        f"[mock] intent={intent.name} metric={metric} time={time_hint} "
        f"platform={platform} docs={[d.doc_id for d in docs]}"
    )
    if feedback:
        prompt += f"\n[retry_feedback] {feedback}"

    # On retry feedback, prefer simpler / safer SELECT (All platform, known tables).
    safer = bool(feedback)

    if metric == "dau":
        table = "ads_dau_daily"
        pred = _date_predicate(time_hint).format(table=table)
        where = [pred]
        if platform and not safer:
            where.append(f"platform = '{platform}'")
        else:
            where.append("platform = 'All'")
        sql = f"SELECT dt, platform, dau FROM {table} WHERE " + " AND ".join(where) + " ORDER BY dt"
    elif metric == "retention":
        table = "ads_retention_daily"
        pred = _date_predicate(time_hint).format(table=table)
        sql = (
            f"SELECT dt, retention_d1, retention_d7 FROM {table} "
            f"WHERE {pred} ORDER BY dt"
        )
    elif metric in ("arpu", "pay_rate", "revenue", "pay_users"):
        table = "ads_revenue_daily"
        pred = _date_predicate(time_hint).format(table=table)
        cols = {
            "arpu": "dt, arpu, revenue, pay_users",
            "pay_rate": "dt, pay_rate, pay_users, revenue",
            "revenue": "dt, revenue, pay_users, arpu, pay_rate",
            "pay_users": "dt, pay_users, revenue, pay_rate",
        }[metric]
        sql = f"SELECT {cols} FROM {table} WHERE {pred} ORDER BY dt"
    else:
        sql = (
            "SELECT dt, platform, dau FROM ads_dau_daily "
            "WHERE dt = (SELECT max(dt) FROM ads_dau_daily) AND platform = 'All' ORDER BY dt"
        )

    # Hard enforce single SELECT (strip any accidental multi-stmt / DDL from feedback paths).
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
        "You are a SQL generator for DuckDB over GameStream-like ADS tables.\n"
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
        # Retry path prefers deterministic mock SELECT for demo reliability.
        if feedback:
            return _mock_sql(intent, docs, feedback=feedback)
        return _openai_sql(intent, docs, settings, feedback=None)
    return _mock_sql(intent, docs, feedback=feedback)
