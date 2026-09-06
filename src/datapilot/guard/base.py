"""SQLGuard client protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GateResult:
    allowed: bool
    action: str  # ALLOW | BLOCK | REQUIRE_APPROVAL
    rule_id: str | None = None
    reason: str = ""
    risk: str | None = None
    raw: Any = None

    @staticmethod
    def allow(reason: str = "ok", rule_id: str | None = None, raw: Any = None) -> "GateResult":
        return GateResult(allowed=True, action="ALLOW", rule_id=rule_id, reason=reason, risk="low", raw=raw)

    @staticmethod
    def block(reason: str, rule_id: str | None = None, risk: str = "high", raw: Any = None) -> "GateResult":
        return GateResult(allowed=False, action="BLOCK", rule_id=rule_id, reason=reason, risk=risk, raw=raw)

    @staticmethod
    def require_approval(reason: str, rule_id: str | None = None, raw: Any = None) -> "GateResult":
        return GateResult(
            allowed=False, action="REQUIRE_APPROVAL", rule_id=rule_id, reason=reason, risk="medium", raw=raw
        )


@runtime_checkable
class SQLGuardClient(Protocol):
    def check(self, sql: str) -> GateResult:
        ...


def build_guard_client(mode: str = "mock") -> SQLGuardClient:
    mode = (mode or "mock").lower()
    if mode in ("write_gate", "sql-write-gate", "real"):
        from datapilot.guard.write_gate_client import WriteGateSQLGuardClient

        return WriteGateSQLGuardClient()
    from datapilot.guard.mock import MockSQLGuardClient

    return MockSQLGuardClient()
