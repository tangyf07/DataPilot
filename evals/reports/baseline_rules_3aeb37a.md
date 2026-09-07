# DataPilot baseline — rules mode (DocPilot launch gate)

- **model/mode**: `rules` (offline heuristic SQL rules; no LLM)
- **dataset_version**: `3aeb37a`
- **gold_hash**: `63a3913a653bd6d0bbeceb3225553b4b370fc4fc99ae12f4b1708ce4aa2181c9`
- **git_sha**: `3aeb37a7e7ce57a216b2206aa49f44ef09364389`
- **split**: `test`
- **n_total**: `12` (execute=10, block=2)
- **timestamp**: `2026-09-07 18:39:03 CST` (`2026-09-07T18:39:03+08:00`)
- **llm_calls**: `none` / **not_real_api**: `true`

## Metrics (heuristic)

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

Rules baseline uses offline keyword/rules SQL generation — **not** a live LLM.
`answer_accuracy` is pattern + result-check heuristic (not LLM-judge).
Gold set was **not** expanded for this gate (test n=12).

JSON: `evals/reports/baseline_rules_test.json`
