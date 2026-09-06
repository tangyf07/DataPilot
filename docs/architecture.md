# Architecture

```
Question → Intent → SchemaRetriever (GameStream mock|real)
        → SQLGenerator → SQLGuard.check
             ├─ BLOCK → feedback retry (once) → safer SELECT
             └─ ALLOW → DuckDB → Validate
                    ├─ fail → feedback retry (once)
                    └─ ok → Conclude + Trace
```

Adapters: `SchemaRetriever`, `SQLGuardClient` (`mock` | `write_gate`). DataPilot is the glue, not a second warehouse.
