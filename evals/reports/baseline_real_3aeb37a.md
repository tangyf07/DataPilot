# DataPilot baseline — real path with FIXTURES (NOT live API)

> **WARNING: Fixture / offline mock run.**  
> `llm_calls=fixture` / `not_real_api=true`  
> Scores below are **NOT** true model performance. No `OPENAI_API_KEY` was present.

- **model/mode**: `real` path patched with `mock-fixture` (`evals/fixtures/mock_llm_responses.json`)
- **real_path**: `mock_fixture`
- **model**: `mock-fixture`
- **dataset_version**: `3aeb37a`
- **gold_hash**: `63a3913a653bd6d0bbeceb3225553b4b370fc4fc99ae12f4b1708ce4aa2181c9`
- **git_sha**: `3aeb37a7e7ce57a216b2206aa49f44ef09364389`
- **split**: `test`
- **n_total**: `12` (execute=10, block=2, skipped=0)
- **timestamp**: `2026-09-07 18:39:03 CST` (`2026-09-07T18:39:03+08:00`)
- **failures**: `0`
- **degraded**: `0`
- **retries**: `0`
- **llm_calls**: `fixture` / **not_real_api**: `true`

## Metrics (fixture — not live model)

| Metric | Value |
| --- | --- |
| answer_accuracy | 1.0000 |
| exec_success_rate | 1.0000 |
| repair_success_rate | n/a (no repair attempts in this split) |
| block_rate | 1.0000 |

### Counts
- answer_ok/scored: 10/10
- exec_ok/scored: 10/10
- repair_ok/scored: 0/0
- block_ok/scored: 2/2

## Honesty note

`OPENAI_API_KEY` missing → used fixture SQL map. Do **not** treat these numbers as GPT/model quality.
Re-run with a real key (`--mode real`) for true model baseline before launch decisions that depend on LLM quality.
Gold set was **not** expanded for this gate (test n=12).

JSON: `evals/reports/baseline_real_fixture_test.json`
