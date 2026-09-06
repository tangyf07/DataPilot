"""Result validation after query."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationResult:
    ok: bool
    row_count: int
    columns: list[str]
    issues: list[str]


def validate_result(columns: list[str], rows: list[tuple[Any, ...]]) -> ValidationResult:
    issues: list[str] = []
    if not columns:
        issues.append("no columns returned")
    if rows is None:
        issues.append("rows is None")
        rows = []
    if len(rows) == 0:
        issues.append("empty result set")
    # null-heavy check
    if rows and columns:
        nulls = 0
        total = 0
        for r in rows:
            for v in r:
                total += 1
                if v is None:
                    nulls += 1
        if total and nulls / total > 0.5:
            issues.append("more than 50% null values")
    ok = len(issues) == 0 or (len(rows) > 0 and "no columns returned" not in issues)
    # empty is soft-fail: still ok=False but pipeline continues
    if len(rows) == 0:
        ok = False
    elif "no columns returned" in issues:
        ok = False
    else:
        ok = True
    return ValidationResult(ok=ok, row_count=len(rows), columns=list(columns), issues=issues)
