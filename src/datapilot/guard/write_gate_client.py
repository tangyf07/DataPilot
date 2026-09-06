"""Adapter to real sql-write-gate 1.1 DataPilot BLOCK/EXECUTE API."""

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
from datapilot.guard.mock import MockSQLGuardClient


class WriteGateSQLGuardClient:
    """SQLGuard 1.1 DataPilot adapter.

    Fallback order:
      1. ``write_gate.datapilot.block_or_execute`` (module)
      2. HTTP POST ``{guard_url}/v1/check`` when URL set
      3. CLI ``sql-write-gate datapilot --json``
      4. MockSQLGuardClient (marked in ``raw``)
    """

    def __init__(
        self,
        *,
        guard_url: str | None = None,
        catalog_path: str | Path | None = None,
        policy_path: str | Path | None = None,
        db_path: str | Path | None = None,
        prefer_http: bool = False,
        actor: str | None = None,
        model_id: str | None = None,
        prompt_summary: str | None = None,
        agent: str = "datapilot",
    ) -> None:
        self._fallback = MockSQLGuardClient()
        self.guard_url = (guard_url or os.getenv("DATAPILOT_GUARD_URL") or "").rstrip("/")
        self.catalog_path = str(catalog_path) if catalog_path else None
        self.policy_path = str(policy_path) if policy_path else None
        self.db_path = str(db_path) if db_path else None
        self.prefer_http = prefer_http
        self.actor = actor
        self.model_id = model_id
        self.prompt_summary = prompt_summary
        self.agent = agent or "datapilot"

        self._block_or_execute = None
        self._backend = "fallback_mock"
        try:
            from write_gate.datapilot import block_or_execute  # type: ignore

            self._block_or_execute = block_or_execute
            self._backend = "write_gate_datapilot"
        except Exception:
            if self.guard_url:
                self._backend = "http"
            elif shutil.which("sql-write-gate"):
                self._backend = "cli"
            else:
                self._backend = "fallback_mock"

    def check(self, sql: str) -> GateResult:
        return self._dispatch(sql, execute=False)

    def execute(self, sql: str) -> GateResult:
        """Optional: call block_or_execute(execute=True). Pipeline still uses check + DuckDB."""
        return self._dispatch(sql, execute=True)

    def _dispatch(self, sql: str, *, execute: bool) -> GateResult:
        order: list[str]
        if self.prefer_http and self.guard_url:
            order = ["http", "module", "cli", "mock"]
        else:
            order = ["module", "http", "cli", "mock"]

        last_err: str | None = None
        for kind in order:
            try:
                if kind == "module" and self._block_or_execute is not None:
                    return self._check_module(sql, execute=execute)
                if kind == "http" and self.guard_url:
                    return self._check_http(sql, execute=execute)
                if kind == "cli" and shutil.which("sql-write-gate"):
                    return self._check_cli(sql, execute=execute)
                if kind == "mock":
                    result = self._fallback.check(sql)
                    note = {
                        "backend": "mock_fallback",
                        "reason": last_err or "sql-write-gate not available",
                        "preferred_backend": self._backend,
                    }
                    if isinstance(result.raw, dict):
                        result.raw = {**result.raw, **note}
                    else:
                        result.raw = note
                    return result
            except Exception as exc:  # noqa: BLE001
                last_err = f"{kind}: {exc}"
                continue

        result = self._fallback.check(sql)
        result.raw = {"backend": "mock_fallback", "reason": last_err or "exhausted"}
        return result

    def _kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {"agent": self.agent}
        if self.catalog_path:
            kw["catalog_path"] = self.catalog_path
        if self.policy_path:
            kw["policy_path"] = self.policy_path
        if self.db_path:
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
        path = "/v1/execute" if execute else "/v1/check"
        url = f"{self.guard_url}{path}"
        body: dict[str, Any] = {"sql": sql, "agent": self.agent}
        if self.catalog_path:
            body["catalog"] = self.catalog_path
        if self.policy_path:
            body["policy"] = self.policy_path
        if self.db_path:
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
        if self.db_path:
            cmd.extend(["--db", self.db_path])
        if self.actor:
            cmd.extend(["--actor", self.actor])
        if self.model_id:
            cmd.extend(["--model-id", self.model_id])
        if self.prompt_summary:
            cmd.extend(["--prompt-summary", self.prompt_summary])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        try:
            payload = json.loads(out)
        except json.JSONDecodeError:
            # Plain-text datapilot CLI: first line is BLOCK|EXECUTE|APPROVAL
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            verb = lines[0].upper() if lines else ("EXECUTE" if proc.returncode == 0 else "BLOCK")
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
            return self._from_fields(
                datapilot=str(dp).upper() if dp else None,
                action=action,
                allowed=bool(getattr(data, "allowed", False)),
                rule_id=getattr(data, "rule_id", None),
                reason=str(getattr(data, "reason", "")),
                risk=getattr(data, "risk", None),
                risk_score=getattr(data, "risk_score", None),
                latency_ms=getattr(data, "latency_ms", None),
                raw={"backend": backend, "payload": data},
            )

        if isinstance(data, dict):
            dp = data.get("datapilot")
            action = str(data.get("action") or "").upper()
            return self._from_fields(
                datapilot=str(dp).upper() if dp else None,
                action=action,
                allowed=bool(data.get("allowed", False)),
                rule_id=data.get("rule_id"),
                reason=str(data.get("reason", "")),
                risk=data.get("risk"),
                risk_score=data.get("risk_score"),
                latency_ms=data.get("latency_ms"),
                raw={"backend": backend, "payload": data},
            )

        return GateResult.block("unrecognized write_gate response", raw={"backend": backend, "payload": data})

    def _from_fields(
        self,
        *,
        datapilot: str | None,
        action: str,
        allowed: bool,
        rule_id: Any,
        reason: str,
        risk: Any,
        risk_score: Any,
        latency_ms: Any,
        raw: Any,
    ) -> GateResult:
        # Prefer datapilot verb when present
        verb = (datapilot or "").upper()
        if verb == "EXECUTE" or action == "ALLOW":
            return GateResult.allow(
                reason=reason or "ok",
                rule_id=rule_id,
                raw=raw,
                datapilot="EXECUTE",
                risk_score=risk_score,
                latency_ms=float(latency_ms) if latency_ms is not None else None,
                risk=str(risk) if risk is not None else "low",
            )
        if verb == "APPROVAL" or action in ("REQUIRE_APPROVAL", "APPROVAL"):
            return GateResult.require_approval(
                reason=reason or "approval required",
                rule_id=rule_id,
                raw=raw,
                datapilot="APPROVAL",
                risk_score=risk_score,
                latency_ms=float(latency_ms) if latency_ms is not None else None,
                risk=str(risk) if risk is not None else "medium",
            )
        # BLOCK or anything else → not allowed
        if not verb:
            verb = "BLOCK"
        return GateResult.block(
            reason=reason or "blocked",
            rule_id=rule_id,
            risk=str(risk) if risk is not None else "high",
            raw=raw,
            datapilot=verb if verb in ("BLOCK", "EXECUTE", "APPROVAL") else "BLOCK",
            risk_score=risk_score,
            latency_ms=float(latency_ms) if latency_ms is not None else None,
        )
