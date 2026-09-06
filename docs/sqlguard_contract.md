# SQLGuard interface contract

Package: `sql-write-gate` ≥ **1.1.0** / import `write_gate` (optional — **do not vendor**).

DataPilot uses the stable **DataPilot BLOCK / EXECUTE** surface for gate verdicts, then still runs SELECT on its own DuckDB warehouse (MVP).

## DataPilot verbs

| `datapilot` | Meaning for DataPilot |
|-------------|------------------------|
| `EXECUTE`   | Allowed to run SQL (maps from Decision `ALLOW`) |
| `BLOCK`     | Do not run |
| `APPROVAL`  | Not auto-execute (treat as not allowed) |

Legacy `action` field remains: `ALLOW` | `BLOCK` | `REQUIRE_APPROVAL`.

## Python API

```python
from write_gate.datapilot import block_or_execute

payload = block_or_execute(
    sql,
    execute=False,           # check-only (preferred for DataPilot MVP)
    agent="datapilot",
    catalog_path="...",      # ADS catalog under data/sqlguard/
    policy_path="...",
)
# payload["datapilot"] in {"BLOCK","EXECUTE","APPROVAL"}
# also: action, rule_id, reason, risk_score, latency_ms, ...
```

`execute=True` runs SQL inside SQLGuard only on ALLOW — DataPilot pipeline keeps **check-then-DuckDB** for now.

## HTTP (`sql-write-gate serve`)

- `POST /v1/check` — evaluate only
- `POST /v1/execute` — evaluate then execute on ALLOW
- Body: `{"sql": "...", "actor"?, "model_id"?, "prompt_summary"?, "catalog"?, "policy"?}`
- Response includes `datapilot`, `action`, `risk_score`, `rule_id`, `reason`, …

Also available: thin `write_gate.datapilot.serve_http` (`POST /v1/datapilot`).

## CLI

```bash
sql-write-gate datapilot "SELECT ..." --json --catalog ... --policy ...
sql-write-gate datapilot "..." --execute   # optional execute on ALLOW
sql-write-gate serve --host 127.0.0.1 --port 8787
```

## DataPilot adapter

```python
class GateResult:
    allowed: bool
    action: str          # ALLOW | BLOCK | REQUIRE_APPROVAL
    rule_id: str | None
    reason: str
    risk: str | None
    raw: Any
    datapilot: str | None     # BLOCK | EXECUTE | APPROVAL
    risk_score: float | None
    latency_ms: float | None

class SQLGuardClient(Protocol):
    def check(self, sql: str) -> GateResult: ...
```

### Implementations / modes (`DATAPILOT_GUARD_MODE`)

| Mode | Behavior |
|------|----------|
| `auto` (default) | Prefer real SQLGuard 1.1 (`block_or_execute` → HTTP → CLI → mock) |
| `write_gate` | Same adapter (explicit) |
| `http` | Prefer `DATAPILOT_GUARD_URL` `POST /v1/check` |
| `mock` | `MockSQLGuardClient` only |

**Mock remains fallback only** when the real package/URL/CLI is unavailable.

Ship ADS catalog + permissive SELECT policy under `data/sqlguard/` so `ads_*` SELECTs are not `schema_hallucination` BLOCKed.
