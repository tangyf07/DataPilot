"""Mock SQLGuard: allow single SELECT; block dangerous writes."""

from __future__ import annotations

import re

from datapilot.guard.base import GateResult


class MockSQLGuardClient:
    """Demo gate mirroring sql-write-gate decision actions."""

    _WRITE_NO_WHERE = re.compile(
        r"^\s*(DELETE|UPDATE)\b(?![\s\S]*\bWHERE\b)",
        re.I,
    )
    _DDL = re.compile(r"\b(DROP|TRUNCATE|ALTER)\b", re.I)

    def check(self, sql: str) -> GateResult:
        text = (sql or "").strip()
        if not text:
            return GateResult.block("empty SQL", rule_id="empty")

        # strip trailing semicolons for statement count
        parts = [p.strip() for p in text.split(";") if p.strip()]
        if len(parts) > 1:
            return GateResult.block("multi-statement not allowed", rule_id="multi_statement")

        stmt = parts[0]
        if self._DDL.search(stmt):
            return GateResult.block("DDL/destructive statement blocked", rule_id="ddl_block", risk="critical")

        if re.match(r"^\s*(DELETE|UPDATE)\b", stmt, re.I):
            if not re.search(r"\bWHERE\b", stmt, re.I):
                return GateResult.block(
                    "DELETE/UPDATE without WHERE blocked",
                    rule_id="write_no_where",
                    risk="critical",
                )
            return GateResult.require_approval("mutating DML needs approval", rule_id="dml_approval")

        if re.match(r"^\s*(INSERT|CREATE|REPLACE|MERGE)\b", stmt, re.I):
            return GateResult.require_approval("write statement needs approval", rule_id="write_approval")

        if re.match(r"^\s*(WITH\b|[\(]*\s*SELECT\b)", stmt, re.I):
            return GateResult.allow(reason="single SELECT allowed", rule_id="select_allow")

        return GateResult.block(f"unsupported statement type", rule_id="unknown_stmt")
