# DataPilot

Intelligent query layer for an AI data-eng stack: **GameStream** (metrics/schema lakehouse) → **DataPilot** (intent → RAG → Text2SQL → explain) → **SQLGuard** (pre-exec gate). Not a bare RAG/ChatBI homework demo.

## Loop

1. Intent recognition  
2. Schema/metrics RAG (`MockGameStreamRetriever`; real GameStream reserved)  
3. Text2SQL (mock rules or OpenAI-compatible)  
4. **SQLGuard** check — on BLOCK, **one feedback retry** (safer SELECT)  
5. DuckDB execute — on query/validation failure, **one feedback retry**  
6. Validate → NL conclusion + ASCII table (optional chart if matplotlib)  
7. Observability trace (`traces/`)

Max attempts: **2** (1 retry).

## Quickstart

```bash
pip install -e ".[dev]"
# optional real gate:
pip install -e ".[sqlguard]"   # or: pip install -e /path/to/sql-write-gate
python -m datapilot demo
python -m datapilot "昨天DAU多少？"
pytest -q
```

No API key needed (`DATAPILOT_LLM_MODE=mock`).

## Env

| Variable | Default | Notes |
|----------|---------|--------|
| `DATAPILOT_LLM_MODE` | `mock` | or `openai` |
| `OPENAI_API_KEY` / `BASE_URL` / `MODEL` | — | OpenAI-compatible |
| `DATAPILOT_DB_PATH` | `./data/datapilot.duckdb` | DuckDB file |
| `DATAPILOT_GUARD_MODE` | `auto` | `auto`\|`write_gate`\|`http`\|`mock` |
| `DATAPILOT_GUARD_URL` | — | HTTP base for `POST /v1/check` |
| `DATAPILOT_GUARD_CATALOG` | `./data/sqlguard/catalog.json` | ADS catalog |
| `DATAPILOT_GUARD_POLICY` | `./data/sqlguard/policy.yaml` | demo SELECT policy |
| `DATAPILOT_TRACE_DIR` | `./traces` | JSON traces |

## DuckDB seed

Tables: `ads_dau_daily`, `ads_retention_daily`, `ads_revenue_daily` (~14 days).

## SQLGuard

Default **`auto`**: prefers real **SQLGuard 1.1** DataPilot `BLOCK`/`EXECUTE` when `sql-write-gate` is installed (module → HTTP → CLI). **Mock** remains fallback only. See `docs/sqlguard_contract.md`.

Ship `data/sqlguard/` so ADS `SELECT`s are not schema-hallucination BLOCKed.

## Layout

`intent` · `rag` · `sql` · `guard` · `query` · `report` · `observe` · `pipeline` · `cli`
