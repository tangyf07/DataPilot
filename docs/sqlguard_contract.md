# SQLGuard interface contract

Package: `sql-write-gate` / import `write_gate` (optional dependency — **do not vendor**).

## Decision actions

- `ALLOW` — `Decision.allowed` is True **only** for ALLOW
- `BLOCK`
- `REQUIRE_APPROVAL`

Prefer check-then-query for SELECT.

## DataPilot adapter

```python
class GateResult:
    allowed: bool
    action: str   # ALLOW | BLOCK | REQUIRE_APPROVAL
    rule_id: str | None
    reason: str
    risk: str | None
    raw: Any

class SQLGuardClient(Protocol):
    def check(self, sql: str) -> GateResult: ...
```

### Implementations

1. `MockSQLGuardClient` — default demo
   - Allow single SELECT
   - Block DROP / TRUNCATE / ALTER
   - Block DELETE|UPDATE without WHERE
   - Block multi-statement
2. `WriteGateSQLGuardClient` — tries `from write_gate...` or CLI `sql-write-gate check`
