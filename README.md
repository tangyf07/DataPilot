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
| `DATAPILOT_GUARD_MODE` | `mock` | or `write_gate` |
| `DATAPILOT_TRACE_DIR` | `./traces` | JSON traces |

## DuckDB seed

Tables: `ads_dau_daily`, `ads_retention_daily`, `ads_revenue_daily` (~14 days).

## SQLGuard

- **mock**: allow single SELECT; block DDL / multi-stmt / DELETE|UPDATE without WHERE  
- **write_gate**: optional `write_gate` / `sql-write-gate` adapter (see `docs/sqlguard_contract.md`)

## Layout

`intent` · `rag` · `sql` · `guard` · `query` · `report` · `observe` · `pipeline` · `cli`
