"""P0: real gate failure must NOT mock-fallback; db_execute_count stays 0."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from datapilot.config import Settings
from datapilot.guard.base import GateResult, build_guard_client
from datapilot.guard.write_gate_client import WriteGateSQLGuardClient
from datapilot.pipeline import Pipeline

pytestmark = [pytest.mark.suite_p0, pytest.mark.suite_gate]

@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    root = Path(__file__).resolve().parents[1] / ".pytest_work" / "gate_fail"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return Settings(
        llm_mode="mock",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=root / "test.duckdb",
        guard_mode="write_gate",
        trace_dir=root / "traces",
        project_root=root,
        guard_url=None,
        guard_catalog=None,
        guard_policy=None,
        query_backend="duckdb",
        doris_url=None,
    )


def test_write_gate_module_raise_blocks_no_db_exec(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force module to raise → pipeline SELECT is blocked/error, query None, db_execute_count==0, no mock."""

    def boom(*_a, **_k):
        raise RuntimeError("injected gate module failure")

    pipe = Pipeline(settings=settings)
    # Ensure we are on WriteGateSQLGuardClient (real mode)
    assert isinstance(pipe.guard, WriteGateSQLGuardClient)
    monkeypatch.setattr(pipe.guard, "_block_or_execute", boom)
    # Disable CLI so only module path is attempted then BLOCK
    monkeypatch.setattr(
        "datapilot.guard.write_gate_client.shutil.which",
        lambda _name: None,
    )

    # Spy: DuckDB engine must not execute
    calls = {"n": 0}
    real_exec = pipe.engine.execute

    def counting_execute(sql: str):
        calls["n"] += 1
        return real_exec(sql)

    monkeypatch.setattr(pipe.engine, "execute", counting_execute)

    result = pipe.run("昨天DAU多少？")

    assert result.query is None
    assert result.blocked is True or result.error is not None or (
        result.gate is not None and not result.gate.allowed
    )
    assert result.db_execute_count == 0
    assert calls["n"] == 0
    assert result.gate is not None
    raw = result.gate.raw if isinstance(result.gate.raw, dict) else {}
    assert raw.get("backend") != "mock_fallback"
    assert raw.get("fallback") is None
    summary = result.summary()
    assert summary["db_execute_count"] == 0
    assert summary["gate"]["backend"] != "mock_fallback"
    assert summary["gate"]["fallback_reason"] is None


def test_build_guard_only_mock_mode_uses_mock() -> None:
    from datapilot.guard.mock import MockSQLGuardClient

    assert isinstance(build_guard_client("mock"), MockSQLGuardClient)
    client = build_guard_client("write_gate")
    assert isinstance(client, WriteGateSQLGuardClient)


def test_field_contradiction_execute_but_block() -> None:
    client = WriteGateSQLGuardClient(mode="write_gate")
    # Bypass backends: call normalize directly
    result = client._normalize(
        {"datapilot": "EXECUTE", "action": "BLOCK", "allowed": False, "reason": "contradiction"},
        backend="write_gate_datapilot",
    )
    assert result.allowed is False
    assert result.action == "BLOCK"
    assert isinstance(result.raw, dict)
    assert result.raw.get("error") == "field_contradiction"
    assert result.raw.get("fallback") is None


def test_http_mode_no_url_blocks_not_mock() -> None:
    client = WriteGateSQLGuardClient(mode="http", prefer_http=True, guard_url=None)
    client._block_or_execute = None
    r = client.check("SELECT 1")
    assert r.allowed is False
    assert isinstance(r.raw, dict)
    assert r.raw.get("backend") != "mock_fallback"
    assert r.raw.get("fallback") is None
