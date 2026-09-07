"""Optional G7 Doris integration: skip unless DATAPILOT_DORIS_URL is reachable."""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest

from datapilot.config import DEFAULT_DORIS_URL, Settings
from datapilot.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "sqlguard" / "catalog.json"
POLICY = ROOT / "data" / "sqlguard" / "policy.yaml"


def _doris_url() -> str:
    return (os.getenv("DATAPILOT_DORIS_URL") or "").strip() or DEFAULT_DORIS_URL


def _reachable(url: str, timeout: float = 1.5) -> bool:
    try:
        p = urlparse(url)
        with socket.create_connection((p.hostname or "127.0.0.1", p.port or 9030), timeout=timeout):
            return True
    except Exception:
        return False


def _require_doris():
    url = _doris_url()
    if not _reachable(url):
        pytest.skip(f"Doris not reachable at {url}")
    pytest.importorskip("pymysql")
    pytest.importorskip("write_gate")
    return url


@pytest.fixture()
def doris_settings(tmp_path: Path) -> Settings:
    url = _require_doris()
    return Settings(
        llm_mode="mock",
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
        db_path=tmp_path / "unused.duckdb",
        guard_mode="write_gate",
        trace_dir=tmp_path / "traces",
        project_root=tmp_path,
        guard_url=None,
        guard_catalog=CATALOG,
        guard_policy=POLICY,
        query_backend="doris",
        doris_url=url,
    )


def test_dau_select_via_guard_returns_rows(doris_settings: Settings) -> None:
    pipe = Pipeline(settings=doris_settings)
    result = pipe.run("昨天/最近 DAU")
    assert result.blocked is False
    assert result.error is None
    assert result.gate is not None
    assert result.gate.datapilot == "EXECUTE" or result.gate.action == "ALLOW"
    assert result.query is not None
    assert len(result.query.rows) >= 1
    assert "dau" in [c.lower() for c in result.query.columns]
    assert result.query_backend == "doris"
    assert result.query_path in (
        "sqlguard_execute",
        "sqlguard_check_then_pymysql",
        "sqlguard_check_then_engine",
    )


def test_pay_rate_select_via_guard(doris_settings: Settings) -> None:
    pipe = Pipeline(settings=doris_settings)
    result = pipe.run("付费率")
    assert result.blocked is False
    assert result.query is not None
    assert len(result.query.rows) >= 1
    cols = [c.lower() for c in result.query.columns]
    assert "pay_rate" in cols or "pay_users" in cols
