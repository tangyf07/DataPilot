"""SQLGuard client protocol and factory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class GateResult:
    allowed: bool
    action: str  # ALLOW | BLOCK | REQUIRE_APPROVAL
    rule_id: str | None = None
    reason: str = ""
    risk: str | None = None
    raw: Any = None
    # SQLGuard 1.1 DataPilot surface (optional, backward compatible)
    datapilot: str | None = None  # BLOCK | EXECUTE | APPROVAL
    risk_score: float | int | None = None
    latency_ms: float | None = None

    @staticmethod
    def allow(
        reason: str = "ok",
        rule_id: str | None = None,
        raw: Any = None,
        *,
        datapilot: str | None = "EXECUTE",
        risk_score: float | int | None = None,
        latency_ms: float | None = None,
        risk: str | None = "low",
    ) -> "GateResult":
        return GateResult(
            allowed=True,
            action="ALLOW",
            rule_id=rule_id,
            reason=reason,
            risk=risk,
            raw=raw,
            datapilot=datapilot,
            risk_score=risk_score,
            latency_ms=latency_ms,
        )

    @staticmethod
    def block(
        reason: str,
        rule_id: str | None = None,
        risk: str = "high",
        raw: Any = None,
        *,
        datapilot: str | None = "BLOCK",
        risk_score: float | int | None = None,
        latency_ms: float | None = None,
    ) -> "GateResult":
        return GateResult(
            allowed=False,
            action="BLOCK",
            rule_id=rule_id,
            reason=reason,
            risk=risk,
            raw=raw,
            datapilot=datapilot,
            risk_score=risk_score,
            latency_ms=latency_ms,
        )

    @staticmethod
    def require_approval(
        reason: str,
        rule_id: str | None = None,
        raw: Any = None,
        *,
        datapilot: str | None = "APPROVAL",
        risk_score: float | int | None = None,
        latency_ms: float | None = None,
        risk: str | None = "medium",
    ) -> "GateResult":
        return GateResult(
            allowed=False,
            action="REQUIRE_APPROVAL",
            rule_id=rule_id,
            reason=reason,
            risk=risk,
            raw=raw,
            datapilot=datapilot,
            risk_score=risk_score,
            latency_ms=latency_ms,
        )


@runtime_checkable
class SQLGuardClient(Protocol):
    def check(self, sql: str) -> GateResult:
        ...


def build_guard_client(
    mode: str = "auto",
    *,
    guard_url: str | None = None,
    catalog_path: str | Path | None = None,
    policy_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> SQLGuardClient:
    """Build a gate client.

    Modes:
      - auto / write_gate: prefer real SQLGuard 1.1 adapter (module → HTTP → CLI → mock)
      - http: force HTTP /v1/check when URL available (else fall through adapter)
      - mock: always MockSQLGuardClient
    """
    mode = (mode or "auto").lower().strip()
    if mode == "mock":
        from datapilot.guard.mock import MockSQLGuardClient

        return MockSQLGuardClient()

    from datapilot.guard.write_gate_client import WriteGateSQLGuardClient

    prefer_http = mode == "http"
    return WriteGateSQLGuardClient(
        guard_url=guard_url,
        catalog_path=catalog_path,
        policy_path=policy_path,
        db_path=db_path,
        prefer_http=prefer_http,
    )
