"""Offline pipeline test: no network, mock LLM, DuckDB, ALLOW gate + retry."""

from __future__ import annotations

from pathlib import Path

import pytest

from datapilot.config import Settings
from datapilot.guard.mock import MockSQLGuardClient
from datapilot.pipeline import Pipeline
from datapilot.sql.generator import SQLGeneration, generate_sql


@pytest.fixture()
def settings() -> Settings:
    # Project-local work dir avoids Windows PermissionError on %TEMP%/pytest-of-*
    import shutil
    root = Path(__file__).resolve().parents[1] / ".pytest_work"
    root.mkdir(exist_ok=True)
    base = root / "offline"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return Settings(
        llm_mode="mock",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=base / "test.duckdb",
        guard_mode="mock",
        trace_dir=base / "traces",
        project_root=base,
        guard_url=None,
        guard_catalog=None,
        guard_policy=None,
    )


def test_dau_pipeline_offline(settings: Settings) -> None:
    pipe = Pipeline(settings=settings)
    result = pipe.run("昨天DAU多少？")

    assert result.intent.metric == "dau"
    assert result.sql_gen is not None
    assert "ads_dau_di" in result.sql_gen.sql.lower()
    assert "metric_id" in result.sql_gen.sql.lower()
    assert "platform" not in result.sql_gen.sql.lower()
    assert result.gate is not None
    assert result.gate.action == "ALLOW"
    assert result.gate.allowed is True
    assert result.blocked is False
    assert result.query is not None
    assert len(result.query.rows) >= 1
    assert "dau" in [c.lower() for c in result.query.columns]
    assert result.validation is not None
    assert result.validation.row_count >= 1
    assert result.report is not None
    assert (
        "DAU" in result.report.conclusion
        or "dau" in result.report.conclusion.lower()
        or "日" in result.report.conclusion
    )
    assert Path(result.trace_path).exists()
    assert result.attempts == 1


def test_gate_block_then_retry(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """First SQL is unsafe (BLOCK); feedback regenerates safe SELECT (ALLOW)."""
    calls = {"n": 0}
    real_generate = generate_sql

    def flaky_generate(intent, docs, settings, feedback=None):
        calls["n"] += 1
        if calls["n"] == 1 and feedback is None:
            return SQLGeneration(
                sql="DROP TABLE ads_dau_di",
                model="mock-rules-v1",
                prompt="[test] unsafe first attempt",
                mode="mock",
            )
        return real_generate(intent, docs, settings, feedback=feedback)

    monkeypatch.setattr("datapilot.pipeline.generate_sql", flaky_generate)

    pipe = Pipeline(settings=settings)
    result = pipe.run("昨天DAU多少？")

    assert calls["n"] == 2
    assert len(result.retries) == 1
    assert result.retries[0]["stage"] == "gate"
    assert result.gate is not None
    assert result.gate.action == "ALLOW"
    assert result.blocked is False
    assert result.query is not None
    assert len(result.query.rows) >= 1
    assert result.attempts == 2
    assert "ads_dau_di" in (result.sql_gen.sql if result.sql_gen else "").lower()


def test_mock_guard_blocks_drop() -> None:
    g = MockSQLGuardClient()
    r = g.check("DROP TABLE ads_dau_di")
    assert r.allowed is False
    assert r.action == "BLOCK"


def test_mock_guard_blocks_multi() -> None:
    g = MockSQLGuardClient()
    r = g.check("SELECT 1; SELECT 2")
    assert r.action == "BLOCK"
