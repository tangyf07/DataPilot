# Architecture

```mermaid
flowchart LR
  GS[GameStream<br/>实时湖仓 ADS] --> DP[DataPilot<br/>智能查数层]
  DP -->|SQL| SG[SQLGuard<br/>sql-write-gate]
  SG -->|EXECUTE| DB[(DuckDB / Doris)]
  SG -->|BLOCK| R[反馈重试]
  R --> DP
```

```
Question → Intent → SchemaRetriever (GameStream mock|real)
        → SQLGenerator → SQLGuard.check
             ├─ BLOCK → feedback retry (once) → safer SELECT
             └─ ALLOW/EXECUTE → DuckDB → Validate
                    ├─ fail → feedback retry (once)
                    └─ ok → Conclude + Trace
```

ADS tables (flat DuckDB names, aligned with GameStream `ads.*`):
`ads_dau_di`, `ads_retention_nd`, `ads_arpu_di`, `ads_pay_rate_di`,
`ads_online_duration_di`, `ads_dungeon_clear_rate_di`, `ads_churn_di`.

Adapters: `SchemaRetriever`, `SQLGuardClient` (`mock` | `write_gate`). DataPilot is the glue, not a second warehouse.
