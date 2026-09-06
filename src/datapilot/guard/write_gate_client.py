"""Optional adapter to real sql-write-gate / write_gate package."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from datapilot.guard.base import GateResult
from datapilot.guard.mock import MockSQLGuardClient


class WriteGateSQLGuardClient:
    """Tries write_gate Python API, then CLI `sql-write-gate check`, else mock fallback."""

    def __init__(self) -> None:
        self._fallback = MockSQLGuardClient()
        self._mode = "fallback_mock"
        self._impl = None
        try:
            import write_gate  # type: ignore

            self._impl = write_gate
            self._mode = "write_gate_module"
        except Exception:
            if shutil.which("sql-write-gate"):
                self._mode = "cli"
            else:
                self._mode = "fallback_mock"

    def check(self, sql: str) -> GateResult:
        if self._mode == "write_gate_module" and self._impl is not None:
            return self._check_module(sql)
        if self._mode == "cli":
            return self._check_cli(sql)
        result = self._fallback.check(sql)
        result.raw = {"backend": "mock_fallback", "reason": "sql-write-gate not installed"}
        return result

    def _normalize(self, data: Any) -> GateResult:
        if isinstance(data, GateResult):
            return data
        if hasattr(data, "allowed") and hasattr(data, "action"):
            action = str(getattr(data, "action", "BLOCK")).upper()
            allowed = bool(getattr(data, "allowed", action == "ALLOW")) and action == "ALLOW"
            return GateResult(
                allowed=allowed,
                action=action if action in ("ALLOW", "BLOCK", "REQUIRE_APPROVAL") else ("ALLOW" if allowed else "BLOCK"),
                rule_id=getattr(data, "rule_id", None),
                reason=str(getattr(data, "reason", "")),
                risk=getattr(data, "risk", None),
                raw=data,
            )
        if isinstance(data, dict):
            action = str(data.get("action", "BLOCK")).upper()
            allowed = bool(data.get("allowed", action == "ALLOW")) and action == "ALLOW"
            return GateResult(
                allowed=allowed,
                action=action,
                rule_id=data.get("rule_id"),
                reason=str(data.get("reason", "")),
                risk=data.get("risk"),
                raw=data,
            )
        return GateResult.block("unrecognized write_gate response", raw=data)

    def _check_module(self, sql: str) -> GateResult:
        wg = self._impl
        for attr in ("check", "check_sql", "evaluate"):
            fn = getattr(wg, attr, None)
            if callable(fn):
                return self._normalize(fn(sql))
        client_cls = getattr(wg, "Client", None) or getattr(wg, "WriteGate", None)
        if client_cls:
            client = client_cls()
            for attr in ("check", "check_sql", "evaluate"):
                fn = getattr(client, attr, None)
                if callable(fn):
                    return self._normalize(fn(sql))
        return self._fallback.check(sql)

    def _check_cli(self, sql: str) -> GateResult:
        try:
            proc = subprocess.run(
                ["sql-write-gate", "check", "--sql", sql, "--format", "json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = proc.stdout.strip() or proc.stderr.strip()
            try:
                data = json.loads(out)
            except json.JSONDecodeError:
                if proc.returncode == 0:
                    return GateResult.allow(reason=out or "cli ok", raw={"stdout": out})
                return GateResult.block(reason=out or "cli blocked", raw={"stdout": out, "code": proc.returncode})
            return self._normalize(data)
        except Exception as exc:  # noqa: BLE001
            result = self._fallback.check(sql)
            result.raw = {"backend": "mock_after_cli_error", "error": str(exc)}
            return result
