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

DataPilot HTTP client uses **only**:

- `POST /v1/check` — evaluate only
- `POST /v1/execute` — evaluate then execute on ALLOW

Never `POST /v1/datapilot`. Body: `{"sql": "...", "actor"?, "model_id"?, "prompt_summary"?, "catalog"?, "policy"?}`.
Response includes `datapilot`, `action`, `risk_score`, `rule_id`, `reason`, …

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
| `auto` (default) | Real SQLGuard 1.1: module → HTTP → CLI; **all fail → BLOCK** (never mock) |
| `write_gate` | Module only (optional CLI same product family); missing module → BLOCK (never mock) |
| `http` | `DATAPILOT_GUARD_URL` only: `POST /v1/check` \| `POST /v1/execute` (never mock / never `/v1/datapilot`) |
| `mock` | `MockSQLGuardClient` only — **only** mode that uses mock |

On timeout / disconnect / ImportError / CLI / HTTP / field contradiction in non-mock modes: return `GateResult.block` with `raw={backend, error, fallback: null}`; pipeline must not execute SQL (`db_execute_count=0`).

Field contradiction: `datapilot=EXECUTE` but `action=BLOCK` (or `allowed=false`) → treat as BLOCK.

Ship ADS catalog + permissive SELECT policy under `data/sqlguard/` so `ads_*` SELECTs are not `schema_hallucination` BLOCKed.
