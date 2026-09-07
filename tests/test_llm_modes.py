"""Honest LLM modes: real / rules / degraded (+ mock/openai aliases)."""

from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from datapilot.config import Settings, normalize_llm_mode
from datapilot.intent import recognize_intent
from datapilot.rag.mock_gamestream import MockGameStreamRetriever
from datapilot.sql.generator import SQLGeneration, generate_sql


def _settings(mode: str, *, key: str | None = None) -> Settings:
    root = Path(__file__).resolve().parents[1] / ".pytest_work" / "llm_modes"
    root.mkdir(parents=True, exist_ok=True)
    base = root / mode.replace("/", "_")
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    return Settings(
        llm_mode=mode,
        openai_api_key=key,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=base / "test.duckdb",
        guard_mode="mock",
        trace_dir=base / "traces",
        project_root=base,
        guard_url=None,
        guard_catalog=None,
        guard_policy=None,
        query_backend="duckdb",
        doris_url=None,
    )


def _intent_docs(q: str = "昨天DAU多少？"):
    intent = recognize_intent(q)
    docs = MockGameStreamRetriever().retrieve(q, intent_name=intent.name, top_k=3)
    return intent, docs


@pytest.mark.parametrize(
    "raw,has_key,expected",
    [
        (None, False, "rules"),
        (None, True, "real"),
        ("", False, "rules"),
        ("mock", False, "rules"),
        ("rules", False, "rules"),
        ("openai", True, "real"),
        ("real", True, "real"),
        ("degraded", False, "degraded"),
        ("MOCK", False, "rules"),
        ("OpenAI", True, "real"),
    ],
)
def test_normalize_llm_mode(raw, has_key, expected) -> None:
    assert normalize_llm_mode(raw, has_api_key=has_key) == expected


def test_rules_mode_and_mock_alias() -> None:
    intent, docs = _intent_docs()
    for mode in ("rules", "mock"):
        gen = generate_sql(intent, docs, _settings(mode))
        assert gen.mode == "rules"
        assert "ads_dau_di" in gen.sql.lower()
        assert gen.degraded_from is None
        assert gen.real_model_error is None


def test_forced_degraded_mode() -> None:
    intent, docs = _intent_docs()
    gen = generate_sql(intent, docs, _settings("degraded"))
    assert gen.mode == "degraded"
    assert gen.degraded_from == "forced"
    assert gen.real_model_error
    assert "ads_dau_di" in gen.sql.lower()


def test_real_without_key_degrades_explicitly() -> None:
    intent, docs = _intent_docs()
    gen = generate_sql(intent, docs, _settings("real", key=None))
    assert gen.mode == "degraded"
    assert gen.degraded_from == "real"
    assert "OPENAI_API_KEY" in (gen.real_model_error or "")
    # Never claim silent real success
    assert gen.mode != "real"


def test_real_feedback_retry_calls_openai_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bugfix: feedback must NOT short-circuit to rules while still in real mode."""
    intent, docs = _intent_docs()
    settings = _settings("real", key="sk-test")
    calls: list[dict] = []

    def fake_real(intent, docs, settings, feedback=None, *, previous_sql=None):
        calls.append({"feedback": feedback, "previous_sql": previous_sql})
        return SQLGeneration(
            sql="SELECT dt, server_id, dau, metric_id FROM ads_dau_di WHERE 1=1",
            model="gpt-4o-mini",
            prompt="fake",
            mode="real",
        )

    monkeypatch.setattr("datapilot.sql.generator._real_sql", fake_real)
    gen = generate_sql(
        intent,
        docs,
        settings,
        feedback="SQLGuard BLOCK: drop not allowed.\nPrevious SQL:\nDROP TABLE x",
        previous_sql="DROP TABLE x",
    )
    assert len(calls) == 1
    assert calls[0]["previous_sql"] == "DROP TABLE x"
    assert calls[0]["feedback"]
    assert gen.mode == "real"


def test_real_api_failure_becomes_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    intent, docs = _intent_docs()
    settings = _settings("openai", key="sk-test")  # alias → real

    fake = types.ModuleType("openai")

    class Boom:
        def __init__(self, *a, **k):
            pass

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

        def create(self, *a, **k):
            raise RuntimeError("upstream 503")

    fake.OpenAI = Boom
    monkeypatch.setitem(sys.modules, "openai", fake)
    gen = generate_sql(intent, docs, settings, feedback="retry me", previous_sql="SELECT 1")
    assert gen.mode == "degraded"
    assert gen.degraded_from == "real"
    assert "503" in (gen.real_model_error or "")
    assert "ads_dau_di" in gen.sql.lower()


def test_pipeline_feedback_includes_previous_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    from datapilot.pipeline import Pipeline

    settings = _settings("rules")
    calls = {"n": 0, "feedbacks": []}
    real_generate = generate_sql

    def flaky(intent, docs, settings, feedback=None, *, previous_sql=None):
        calls["n"] += 1
        calls["feedbacks"].append({"feedback": feedback, "previous_sql": previous_sql})
        if calls["n"] == 1:
            return SQLGeneration(
                sql="DROP TABLE ads_dau_di",
                model="rules-v1",
                prompt="[test] unsafe",
                mode="rules",
            )
        return real_generate(
            intent, docs, settings, feedback=feedback, previous_sql=previous_sql
        )

    monkeypatch.setattr("datapilot.pipeline.generate_sql", flaky)
    result = Pipeline(settings=settings).run("昨天DAU多少？")
    assert calls["n"] == 2
    assert calls["feedbacks"][1]["previous_sql"] == "DROP TABLE ads_dau_di"
    assert "Previous SQL" in (calls["feedbacks"][1]["feedback"] or "")
    assert result.gate and result.gate.allowed
    assert result.sql_gen and result.sql_gen.mode == "rules"


def test_pipeline_counts_real_model_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from datapilot.pipeline import Pipeline
    import json

    settings = _settings("real", key="sk-test")

    def always_degrade(intent, docs, settings, feedback=None, *, previous_sql=None):
        return SQLGeneration(
            sql=(
                "SELECT dt, server_id, dau, metric_id FROM ads_dau_di "
                "WHERE dt = current_date - INTERVAL 1 DAY ORDER BY dt, server_id"
            ),
            model="rules-v1",
            prompt="degraded",
            mode="degraded",
            degraded_from="real",
            real_model_error="timeout",
        )

    monkeypatch.setattr("datapilot.pipeline.generate_sql", always_degrade)
    result = Pipeline(settings=settings).run("昨天DAU多少？")
    assert result.sql_gen and result.sql_gen.mode == "degraded"
    trace = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
    assert trace["meta"]["llm_mode"] == "degraded"
    assert trace["meta"]["real_model_failures"] >= 1
    assert trace["meta"]["real_model_error"] == "timeout"
