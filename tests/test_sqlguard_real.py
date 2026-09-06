"""Real SQLGuard 1.1 DataPilot adapter tests (skip if write_gate missing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from datapilot.guard.write_gate_client import WriteGateSQLGuardClient

pytest.importorskip("write_gate")
pytest.importorskip("write_gate.datapilot")

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "sqlguard" / "catalog.json"
POLICY = ROOT / "data" / "sqlguard" / "policy.yaml"


@pytest.fixture()
def client() -> WriteGateSQLGuardClient:
    assert CATALOG.exists(), f"missing {CATALOG}"
    assert POLICY.exists(), f"missing {POLICY}"
    return WriteGateSQLGuardClient(
        catalog_path=CATALOG,
        policy_path=POLICY,
        agent="datapilot",
    )


def test_select_ads_execute(client: WriteGateSQLGuardClient) -> None:
    r = client.check(
        "SELECT dau, platform FROM ads_dau_daily WHERE platform = 'All' ORDER BY dt DESC LIMIT 1"
    )
    assert r.datapilot == "EXECUTE"
    assert r.action == "ALLOW"
    assert r.allowed is True
    assert r.risk_score is not None


def test_delete_ads_block(client: WriteGateSQLGuardClient) -> None:
    r = client.check("DELETE FROM ads_dau_daily")
    assert r.datapilot == "BLOCK"
    assert r.action == "BLOCK"
    assert r.allowed is False


def test_drop_ads_block(client: WriteGateSQLGuardClient) -> None:
    r = client.check("DROP TABLE ads_dau_daily")
    assert r.datapilot == "BLOCK"
    assert r.allowed is False
