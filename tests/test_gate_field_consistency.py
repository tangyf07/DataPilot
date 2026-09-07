"""P0: reject inconsistent gate fields; empty CLI output is protocol error."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from datapilot.guard.write_gate_client import WriteGateSQLGuardClient

pytestmark = [pytest.mark.suite_p0, pytest.mark.suite_gate]


def _client() -> WriteGateSQLGuardClient:
    return WriteGateSQLGuardClient(mode="write_gate")


def _assert_reject(result) -> None:
    assert result.allowed is False
    assert result.action != "ALLOW"
    assert (result.datapilot or "").upper() != "EXECUTE"
    assert isinstance(result.raw, dict)
    assert result.raw.get("fallback") is None
    assert result.raw.get("backend") != "mock_fallback"
    assert result.raw.get("backend") != "mock"


# (datapilot, action, allowed, expect_reject)
# allowed: True / False / None (key omitted)
FIELD_CASES = [
    # Must BLOCK / protocol error
    ("BLOCK", "ALLOW", False, True),
    ("APPROVAL", "ALLOW", None, True),
    ("EXECUTE", "REQUIRE_APPROVAL", None, True),
    ("EXECUTE", "ALLOW", False, True),  # action=ALLOW + allowed=false
    (None, "ALLOW", False, True),  # regardless of datapilot
    ("BLOCK", "ALLOW", True, True),  # conflicting datapilot + ALLOW
    # Existing: EXECUTE + BLOCK + allowed=false
    ("EXECUTE", "BLOCK", False, True),
    # Happy path
    ("EXECUTE", "ALLOW", True, False),
]


@pytest.mark.parametrize(
    "datapilot,action,allowed,expect_reject",
    FIELD_CASES,
    ids=[
        "block+allow+false",
        "approval+allow",
        "execute+require_approval",
        "allow+allowed_false",
        "no_dp+allow+false",
        "block+allow+true",
        "execute+block+false",
        "happy_execute_allow_true",
    ],
)
def test_from_fields_consistency(
    datapilot: str | None,
    action: str,
    allowed: bool | None,
    expect_reject: bool,
) -> None:
    client = _client()
    result = client._from_fields(
        datapilot=datapilot,
        action=action,
        allowed=allowed,
        rule_id=None,
        reason="test",
        risk=None,
        risk_score=None,
        latency_ms=None,
        raw={"backend": "write_gate_datapilot", "fallback": None},
    )
    if expect_reject:
        _assert_reject(result)
        assert result.raw.get("error") in (
            "field_contradiction",
            "protocol_error",
            None,
        ) or result.rule_id in ("field_contradiction", "protocol_error")
    else:
        assert result.allowed is True
        assert result.action == "ALLOW"
        assert (result.datapilot or "").upper() == "EXECUTE"
        assert result.raw.get("fallback") is None
        assert result.raw.get("backend") != "mock_fallback"


@pytest.mark.parametrize(
    "datapilot,action,allowed,expect_reject",
    FIELD_CASES,
    ids=[
        "block+allow+false",
        "approval+allow",
        "execute+require_approval",
        "allow+allowed_false",
        "no_dp+allow+false",
        "block+allow+true",
        "execute+block+false",
        "happy_execute_allow_true",
    ],
)
def test_normalize_consistency(
    datapilot: str | None,
    action: str,
    allowed: bool | None,
    expect_reject: bool,
) -> None:
    client = _client()
    payload: dict = {"action": action, "reason": "test"}
    if datapilot is not None:
        payload["datapilot"] = datapilot
    if allowed is not None:
        payload["allowed"] = allowed
    result = client._normalize(payload, backend="write_gate_datapilot")
    if expect_reject:
        _assert_reject(result)
    else:
        assert result.allowed is True
        assert result.action == "ALLOW"
        assert (result.datapilot or "").upper() == "EXECUTE"
    assert isinstance(result.raw, dict)
    assert result.raw.get("backend") == "write_gate_datapilot"
    assert result.raw.get("fallback") is None
    assert result.raw.get("backend") != "mock"


def test_cli_empty_stdout_stderr_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client()
    monkeypatch.setattr(
        "datapilot.guard.write_gate_client.shutil.which",
        lambda _name: "/usr/bin/sql-write-gate",
    )

    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = ""
    fake.stderr = ""
    monkeypatch.setattr(
        "datapilot.guard.write_gate_client.subprocess.run",
        lambda *_a, **_k: fake,
    )

    result = client._check_cli("SELECT 1", execute=False)
    _assert_reject(result)
    assert "empty" in (result.reason or "").lower() or result.rule_id == "protocol_error"
    assert isinstance(result.raw, dict)
    assert result.raw.get("error") == "empty_cli_output"
    assert result.raw.get("backend") == "cli"
    assert result.raw.get("fallback") is None


def test_normalize_object_with_contradiction() -> None:
    client = _client()
    obj = SimpleNamespace(
        datapilot="EXECUTE",
        action="BLOCK",
        allowed=False,
        rule_id=None,
        reason="obj contradiction",
        risk=None,
        risk_score=None,
        latency_ms=None,
        executed=False,
        rows=None,
        rowcount=None,
        columns=None,
    )
    result = client._normalize(obj, backend="write_gate_datapilot")
    _assert_reject(result)
