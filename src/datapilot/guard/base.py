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
    # execute path extras
    executed: bool = False
    rows: list[Any] | None = None
    rowcount: int | None = None
    columns: list[str] | None = None

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
        executed: bool = False,
        rows: list[Any] | None = None,
        rowcount: int | None = None,
        columns: list[str] | None = None,
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
            executed=executed,
            rows=rows,
            rowcount=rowcount,
            columns=columns,
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


class GateError(Exception):
    """Raised when a real gate backend fails and the pipeline must not execute SQL."""

    def __init__(self, message: str, *, raw: Any = None) -> None:
        super().__init__(message)
        self.raw = raw


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
    database_url: str | None = None,
) -> SQLGuardClient:
    """Build a gate client.

    Modes:
      - mock: always MockSQLGuardClient (only mode that uses mock)
      - http: HTTP ``/v1/check`` | ``/v1/execute`` only — never mock
      - write_gate: module (optional CLI) — never mock; missing module → BLOCK
      - auto: module → http → cli; all fail → BLOCK (never mock)
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
        database_url=database_url,
        prefer_http=prefer_http,
        mode=mode,
    )
