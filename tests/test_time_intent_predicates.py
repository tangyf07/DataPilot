"""P1: time intent predicates (Asia/Shanghai business calendar)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import shutil

import pytest

from datapilot.config import Settings
from datapilot.intent import recognize_intent
from datapilot.pipeline import Pipeline
from datapilot.rag.mock_gamestream import MockGameStreamRetriever
from datapilot.sql.generator import _date_predicate, generate_sql


@pytest.fixture()
def settings() -> Settings:
    root = Path(__file__).resolve().parents[1] / ".pytest_work" / "time_intent"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return Settings(
        llm_mode="mock",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=root / "test.duckdb",
        guard_mode="mock",
        trace_dir=root / "traces",
        project_root=root,
        guard_url=None,
        guard_catalog=None,
        guard_policy=None,
        query_backend="duckdb",
        doris_url=None,
    )


@pytest.mark.parametrize(
    "question,hint,needle",
    [
        ("昨天DAU", "yesterday", "current_date - INTERVAL 1 DAY"),
        ("今天DAU", "today", "current_date"),
        ("近7天DAU", "last_7_days", "INTERVAL 6 DAY"),
        ("昨天付费率", "yesterday", "current_date - INTERVAL 1 DAY"),
        ("今天付费率", "today", "current_date"),
        ("近7天付费率", "last_7_days", "INTERVAL 6 DAY"),
    ],
)
def test_intent_sql_contains_time_predicate(settings: Settings, question: str, hint: str, needle: str) -> None:
    intent = recognize_intent(question)
    assert intent.time_hint == hint
    docs = MockGameStreamRetriever().retrieve(question, intent_name=intent.name)
    gen = generate_sql(intent, docs, settings)
    sql = gen.sql
    assert needle in sql or needle.lower() in sql.lower()
    # last_7 must be 6-day offset (inclusive [today-6, today]), not 7
    if hint == "last_7_days":
        assert "INTERVAL 7 DAY" not in sql.upper().replace("INTERVAL 6 DAY", "")
        assert "INTERVAL 6 DAY" in sql.upper()


@pytest.mark.parametrize(
    "question,hint",
    [
        ("昨天DAU", "yesterday"),
        ("今天DAU", "today"),
        ("近7天DAU", "last_7_days"),
        ("昨天付费率", "yesterday"),
        ("近7天付费率", "last_7_days"),
    ],
)
def test_doris_portable_sql_attaches_date_predicate(question: str, hint: str) -> None:
    settings = Settings(
        llm_mode="mock",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=Path("/tmp/unused.duckdb"),
        guard_mode="mock",
        trace_dir=Path("/tmp/traces"),
        project_root=Path("/tmp"),
        query_backend="doris",
        doris_url="mysql://root@127.0.0.1:9030/ads",
    )
    intent = recognize_intent(question)
    assert intent.time_hint == hint
    docs = MockGameStreamRetriever().retrieve(question, intent_name=intent.name)
    gen = generate_sql(intent, docs, settings)
    sql = gen.sql.upper()
    assert "DATE_SUB" in sql or "CURRENT_DATE()" in sql
    if hint == "yesterday":
        assert "INTERVAL 1 DAY" in sql
    if hint == "today":
        assert "CURRENT_DATE()" in sql
    if hint == "last_7_days":
        assert "INTERVAL 6 DAY" in sql
        assert "INTERVAL 7 DAY" not in sql.replace("INTERVAL 6 DAY", "")


def test_last_7_days_window_definition() -> None:
    pred = _date_predicate("last_7_days", dialect="duckdb")
    assert "INTERVAL 6 DAY" in pred
    pred_m = _date_predicate("last_7_days", dialect="mysql")
    assert "INTERVAL 6 DAY" in pred_m


def test_duckdb_result_dt_subset_of_window(settings: Settings) -> None:
    """Offline DuckDB: result dt set ⊆ expected inclusive window (do not widen)."""
    pipe = Pipeline(settings=settings)
    today = date.today()
    cases = [
        ("昨天DAU多少？", {today - timedelta(days=1)}),
        ("今天DAU多少？", {today}),
        (
            "近7天DAU多少？",
            {today - timedelta(days=i) for i in range(0, 7)},
        ),
    ]
    for question, expected in cases:
        result = pipe.run(question)
        assert result.blocked is False
        assert result.query is not None
        assert result.sql_gen is not None
        # SQL text predicate present
        if "昨天" in question:
            assert "INTERVAL 1 DAY" in result.sql_gen.sql.upper() or "interval 1 day" in result.sql_gen.sql.lower()
        if "近7天" in question:
            assert "INTERVAL 6 DAY" in result.sql_gen.sql.upper()
        dt_idx = [c.lower() for c in result.query.columns].index("dt")
        dts = set()
        for row in result.query.rows:
            v = row[dt_idx]
            if hasattr(v, "isoformat"):
                dts.add(v if isinstance(v, date) else v)
            else:
                dts.add(date.fromisoformat(str(v)[:10]))
        assert dts, f"no rows for {question}"
        assert dts <= expected, f"{question}: {dts} not ⊆ {expected}"
