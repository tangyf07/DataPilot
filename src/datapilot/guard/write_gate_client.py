"""Adapter to real sql-write-gate 1.1 DataPilot BLOCK/EXECUTE API.

Real modes (write_gate / http / auto / module path) NEVER fall back to
MockSQLGuardClient. Failures return GateResult.block with
``raw={backend, error, fallback: null}``.
Only ``DATAPILOT_GUARD_MODE=mock`` uses MockSQLGuardClient (via factory).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from datapilot.guard.base import GateResult


class WriteGateSQLGuardClient:
    """SQLGuard 1.1 DataPilot adapter (no mock fallback).

    Backend order by mode:
      - http: HTTP only (``/v1/check`` | ``/v1/execute``)
      - write_gate: module, then optional CLI (same product family); no mock
      - auto: module → http → cli; if all fail → BLOCK (not mock)

    When ``database_url`` / ``database`` is a mysql:// Doris URL, execute=True
    runs SELECT through WriteGate MySQL adapter and returns rows in the payload.
    """

    def __init__(
        self,
        *,
        guard_url: str | None = None,
        catalog_path: str | Path | None = None,
        policy_path: str | Path | None = None,
        db_path: str | Path | None = None,
        database_url: str | None = None,
        database: str | None = None,
        prefer_http: bool = False,
        mode: str = "auto",
        actor: str | None = None,
        model_id: str | None = None,
        prompt_summary: str | None = None,
        agent: str = "datapilot",
    ) -> None:
        self.mode = (mode or "auto").lower().strip()
        self.guard_url = (guard_url or os.getenv("DATAPILOT_GUARD_URL") or "").rstrip("/")
        self.catalog_path = str(catalog_path) if catalog_path else None
        self.policy_path = str(policy_path) if policy_path else None
        self.db_path = str(db_path) if db_path else None
        self.database_url = (
            database_url
            or database
            or os.getenv("DATAPILOT_DORIS_URL")
            or None
        )
        self.prefer_http = prefer_http or self.mode == "http"
        self.actor = actor
        self.model_id = model_id
        self.prompt_summary = prompt_summary
        self.agent = agent or "datapilot"

        self._block_or_execute = None
        self._backend = "none"
        if self.mode != "http":
            try:
                from write_gate.datapilot import block_or_execute  # type: ignore

                self._block_or_execute = block_or_execute
                self._backend = "write_gate_datapilot"
            except Exception:
                if self.guard_url and self.mode == "auto":
                    self._backend = "http"
                elif shutil.which("sql-write-gate"):
                    self._backend = "cli"
                else:
                    self._backend = "none"
        elif self.guard_url:
            self._backend = "http"

    def check(self, sql: str) -> GateResult:
        return self._dispatch(sql, execute=False)

    def execute(self, sql: str) -> GateResult:
        """Call block_or_execute(execute=True); rows/rowcount on ALLOW+executed."""
        return self._dispatch(sql, execute=True)

    def _backend_order(self) -> list[str]:
        if self.mode == "http" or self.prefer_http and self.mode == "http":
            return ["http"]
        if self.mode == "write_gate":
            return ["module", "cli"]
        # auto and other non-mock real modes
        if self.prefer_http:
            return ["http", "module", "cli"]
        return ["module", "http", "cli"]

    def _fail(self, *, backend: str, error: str) -> GateResult:
        return GateResult.block(
            reason=error,
            rule_id="gate_unavailable",
            raw={"backend": backend, "error": error, "fallback": None},
        )

    def _dispatch(self, sql: str, *, execute: bool) -> GateResult:
        order = self._backend_order()
        last_err: str | None = None
        last_backend: str = self.mode or "none"
        attempted = False

        for kind in order:
            try:
                if kind == "module":
                    if self._block_or_execute is None:
                        if self.mode == "write_gate":
                            # Module required for write_gate; try CLI next if present
                            last_err = "write_gate module not installed"
                            last_backend = "module"
                            continue
                        continue
                    attempted = True
                    return self._check_module(sql, execute=execute)
                if kind == "http":
                    if not self.guard_url:
                        if self.mode == "http":
                            return self._fail(
                                backend="http",
                                error="DATAPILOT_GUARD_URL not set for http mode",
                            )
                        continue
                    attempted = True
                    return self._check_http(sql, execute=execute)
                if kind == "cli":
                    if not shutil.which("sql-write-gate"):
                        continue
                    attempted = True
                    return self._check_cli(sql, execute=execute)
            except Exception as exc:  # noqa: BLE001
                last_err = f"{kind}: {exc}"
                last_backend = kind
                # Real modes: do not fall through to mock; try next real backend
                continue

        if self.mode == "write_gate" and self._block_or_execute is None and not attempted:
            return self._fail(
                backend="module",
                error=last_err or "write_gate module missing; mock fallback disabled",
            )

        return self._fail(
            backend=last_backend,
            error=last_err
            or f"SQLGuard unavailable (mode={self.mode}, attempted={attempted})",
        )

    def _kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"agent": self.agent}
        if self.catalog_path:
            kw["catalog_path"] = self.catalog_path
        if self.policy_path:
            kw["policy_path"] = self.policy_path
        if self.database_url:
            kw["database"] = self.database_url
        elif self.db_path:
            kw["db_path"] = self.db_path
        if self.actor:
            kw["actor"] = self.actor
        if self.model_id:
            kw["model_id"] = self.model_id
        if self.prompt_summary:
            kw["prompt_summary"] = self.prompt_summary
        return kw

    def _check_module(self, sql: str, *, execute: bool) -> GateResult:
        assert self._block_or_execute is not None
        payload = self._block_or_execute(sql, execute=execute, **self._kwargs())
        return self._normalize(payload, backend="write_gate_datapilot")

    def _check_http(self, sql: str, *, execute: bool) -> GateResult:
        # Contract: check → /v1/check ; execute → /v1/execute ; never /v1/datapilot
        path = "/v1/execute" if execute else "/v1/check"
        url = f"{self.guard_url}{path}"
        body: dict[str, Any] = {"sql": sql, "agent": self.agent, "execute": execute}
        if self.catalog_path:
            body["catalog"] = self.catalog_path
            body["catalog_path"] = self.catalog_path
        if self.policy_path:
            body["policy"] = self.policy_path
            body["policy_path"] = self.policy_path
        if self.database_url:
            body["database"] = self.database_url
        elif self.db_path:
            body["db_path"] = self.db_path
        if self.actor:
            body["actor"] = self.actor
        if self.model_id:
            body["model_id"] = self.model_id
        if self.prompt_summary:
            body["prompt_summary"] = self.prompt_summary
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as jde:
                raise RuntimeError(f"HTTP {exc.code}: {raw}") from jde
        return self._normalize(payload, backend="http")

    def _check_cli(self, sql: str, *, execute: bool) -> GateResult:
        cmd = ["sql-write-gate", "datapilot", sql, "--json", "--agent", self.agent]
        if execute:
            cmd.append("--execute")
        if self.catalog_path:
            cmd.extend(["--catalog", self.catalog_path])
        if self.policy_path:
            cmd.extend(["--policy", self.policy_path])
        if self.database_url:
            cmd.extend(["--database", self.database_url])
        elif self.db_path:
            cmd.extend(["--db", self.db_path])
        if self.actor:
            cmd.extend(["--actor", self.actor])
        if self.model_id:
            cmd.extend(["--model-id", self.model_id])
        if self.prompt_summary:
            cmd.extend(["--prompt-summary", self.prompt_summary])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        # Protocol error: success exit with totally empty streams must never become EXECUTE
        if proc.returncode == 0 and not stdout and not stderr:
            return GateResult.block(
                reason="protocol error: empty CLI output",
                rule_id="protocol_error",
                raw={
                    "backend": "cli",
                    "error": "empty_cli_output",
                    "fallback": None,
                    "returncode": proc.returncode,
                },
                datapilot="BLOCK",
            )
        out = stdout or stderr
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            verb = lines[0].upper() if lines else "BLOCK"
            payload = {
                "datapilot": verb if verb in ("BLOCK", "EXECUTE", "APPROVAL") else "BLOCK",
                "action": "ALLOW" if verb == "EXECUTE" else ("REQUIRE_APPROVAL" if verb == "APPROVAL" else "BLOCK"),
                "reason": out or f"cli exit {proc.returncode}",
                "rule_id": None,
            }
        return self._normalize(payload, backend="cli")

    def _normalize(self, data: Any, *, backend: str = "write_gate") -> GateResult:
        if isinstance(data, GateResult):
            return data

        if hasattr(data, "allowed") and hasattr(data, "action") and not isinstance(data, dict):
            action = str(getattr(data, "action", "BLOCK")).upper()
            dp = getattr(data, "datapilot", None)
            # Preserve tri-state allowed (None = absent) for consistency checks
            if hasattr(data, "allowed"):
                allowed_raw = getattr(data, "allowed")
                allowed: bool | None = None if allowed_raw is None else bool(allowed_raw)
            else:
                allowed = None
            return self._from_fields(
                datapilot=str(dp).upper() if dp else None,
                action=action,
                allowed=allowed,
                rule_id=getattr(data, "rule_id", None),
                reason=str(getattr(data, "reason", "")),
                risk=getattr(data, "risk", None),
                risk_score=getattr(data, "risk_score", None),
                latency_ms=getattr(data, "latency_ms", None),
                executed=bool(getattr(data, "executed", False)),
                rows=getattr(data, "rows", None),
                rowcount=getattr(data, "rowcount", None),
                columns=getattr(data, "columns", None),
                raw={"backend": backend, "payload": data, "fallback": None},
            )

        if isinstance(data, dict):
            dp = data.get("datapilot")
            action = str(data.get("action") or "").upper()
            # Tri-state: only coerce when key present; absent stays None
            if "allowed" in data:
                av = data.get("allowed")
                allowed = None if av is None else bool(av)
            else:
                allowed = None
            return self._from_fields(
                datapilot=str(dp).upper() if dp else None,
                action=action,
                allowed=allowed,
                rule_id=data.get("rule_id"),
                reason=str(data.get("reason", "")),
                risk=data.get("risk"),
                risk_score=data.get("risk_score"),
                latency_ms=data.get("latency_ms"),
                executed=bool(data.get("executed", False)),
                rows=data.get("rows"),
                rowcount=data.get("rowcount"),
                columns=data.get("columns"),
                raw={"backend": backend, "payload": data, "fallback": None},
            )

        return GateResult.block(
            "unrecognized write_gate response",
            raw={"backend": backend, "payload": data, "error": "unrecognized", "fallback": None},
        )

    def _from_fields(
        self,
        *,
        datapilot: str | None,
        action: str,
        allowed: bool | None,
        rule_id: Any,
        reason: str,
        risk: Any,
        risk_score: Any,
        latency_ms: Any,
        raw: Any,
        executed: bool = False,
        rows: Any = None,
        rowcount: Any = None,
        columns: Any = None,
    ) -> GateResult:
        """Map gate fields to GateResult with reject-first consistency.

        Contradictions (datapilot vs action vs allowed) always BLOCK — never
        upgrade to ALLOW/EXECUTE. Only consistent EXECUTE/ALLOW paths allow.
        """
        verb = (datapilot or "").upper()
        action_u = (action or "").upper()
        cols = list(columns) if isinstance(columns, (list, tuple)) else None
        row_list = list(rows) if isinstance(rows, (list, tuple)) else None
        rc = int(rowcount) if rowcount is not None else (len(row_list) if row_list is not None else None)

        raw_dict = raw if isinstance(raw, dict) else {"payload": raw}
        lat = float(latency_ms) if latency_ms is not None else None

        def _block(msg: str, *, rule: str = "field_contradiction") -> GateResult:
            return GateResult.block(
                reason=reason or msg,
                rule_id=rule_id or rule,
                risk=str(risk) if risk is not None else "high",
                raw={**raw_dict, "error": rule, "fallback": None},
                datapilot="BLOCK",
                risk_score=risk_score,
                latency_ms=lat,
            )

        # --- Reject-first: field / protocol contradictions ---
        # action=ALLOW + allowed=false (any datapilot, including conflicting)
        if action_u == "ALLOW" and allowed is False:
            return _block("field contradiction: action=ALLOW but allowed=false")
        # datapilot=BLOCK + action=ALLOW (+ typically allowed=false already covered)
        if verb == "BLOCK" and action_u == "ALLOW":
            return _block("field contradiction: datapilot=BLOCK but action=ALLOW")
        # datapilot=APPROVAL + action=ALLOW
        if verb == "APPROVAL" and action_u == "ALLOW":
            return _block("field contradiction: datapilot=APPROVAL but action=ALLOW")
        # datapilot=EXECUTE + action=BLOCK or allowed=false
        if verb == "EXECUTE" and (action_u == "BLOCK" or allowed is False):
            return _block("field contradiction: datapilot=EXECUTE but blocked")
        # datapilot=EXECUTE + action=REQUIRE_APPROVAL (allowed missing or otherwise)
        if verb == "EXECUTE" and action_u in ("REQUIRE_APPROVAL", "APPROVAL"):
            return _block(
                "field contradiction: datapilot=EXECUTE but action=REQUIRE_APPROVAL"
            )
        # datapilot=BLOCK/APPROVAL with allowed=true while claiming execute-ish action
        if verb in ("BLOCK", "APPROVAL") and allowed is True and action_u == "ALLOW":
            return _block(
                f"field contradiction: datapilot={verb} but allowed=true/action=ALLOW"
            )

        # --- Consistent ALLOW / EXECUTE only ---
        # Happy: datapilot=EXECUTE + action=ALLOW + allowed!=false
        # Or: datapilot=EXECUTE + allowed true/absent + action empty or ALLOW
        if verb == "EXECUTE" and allowed is not False and action_u in ("", "ALLOW"):
            return GateResult.allow(
                reason=reason or "ok",
                rule_id=rule_id,
                raw={**raw_dict, "fallback": None},
                datapilot="EXECUTE",
                risk_score=risk_score,
                latency_ms=lat,
                risk=str(risk) if risk is not None else "low",
                executed=bool(executed),
                rows=row_list,
                rowcount=rc,
                columns=cols,
            )
        # No datapilot verb: action=ALLOW + allowed!=false is consistent allow
        if not verb and action_u == "ALLOW" and allowed is not False:
            return GateResult.allow(
                reason=reason or "ok",
                rule_id=rule_id,
                raw={**raw_dict, "fallback": None},
                datapilot="EXECUTE",
                risk_score=risk_score,
                latency_ms=lat,
                risk=str(risk) if risk is not None else "low",
                executed=bool(executed),
                rows=row_list,
                rowcount=rc,
                columns=cols,
            )

        # Consistent APPROVAL (not mixed with ALLOW/EXECUTE — those rejected above)
        if verb == "APPROVAL" or action_u in ("REQUIRE_APPROVAL", "APPROVAL"):
            return GateResult.require_approval(
                reason=reason or "approval required",
                rule_id=rule_id,
                raw={**raw_dict, "fallback": None},
                datapilot="APPROVAL",
                risk_score=risk_score,
                latency_ms=lat,
                risk=str(risk) if risk is not None else "medium",
            )

        if not verb:
            verb = "BLOCK"
        return GateResult.block(
            reason=reason or "blocked",
            rule_id=rule_id,
            risk=str(risk) if risk is not None else "high",
            raw={**raw_dict, "fallback": None},
            datapilot=verb if verb in ("BLOCK", "EXECUTE", "APPROVAL") else "BLOCK",
            risk_score=risk_score,
            latency_ms=lat,
        )
