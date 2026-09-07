# DataPilot REAL baseline — DeepSeek

- timestamp_utc: `2026-09-07T10:49:34Z`
- provider: `deepseek`
- model: `deepseek-chat`
- base_url: `https://api.deepseek.com/v1`
- commit_sha: `932bde171e0587fa805381dea8ab3e97d047141f`
- mode: `real`
- split: `test`
- real_path: `openai`
- not_real_api: `false`
- llm_calls: `live`
- openai_api_key_set: `true`
- n_total: `12`
- n_execute: `10`
- n_block: `2`
- n_skipped: `0`

## Metrics

| metric | value |
|---|---|
| answer_accuracy | 0.9 |
| exec_success_rate | 1.0 |
| repair_success_rate | None |
| block_rate | 1.0 |

- counts: `{"answer_ok": 9, "answer_scored": 10, "exec_ok": 10, "exec_scored": 10, "repair_ok": 0, "repair_scored": 0, "block_ok": 2, "block_scored": 2}`
- failed_item_ids: `['g034']`
- degraded_count: `0`
- retry_stats: `{"n_retried": 0, "retried_items": [], "repair_success_rate": null, "repair_n": 0}`

> Honesty: live DeepSeek OpenAI-compatible API (`not_real_api=false`, `llm_calls=live`). Not fixture/mock.

