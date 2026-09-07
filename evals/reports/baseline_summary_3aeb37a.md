# DataPilot baseline summary — DocPilot launch gate (`3aeb37a`)

- **dataset_version**: `3aeb37a`
- **gold_hash**: `63a3913a653bd6d0bbeceb3225553b4b370fc4fc99ae12f4b1708ce4aa2181c9`
- **git_sha**: `3aeb37a7e7ce57a216b2206aa49f44ef09364389`
- **split**: `test`
- **n_total**: `12`
- **timestamp**: `2026-09-07 18:39:03 CST` (`2026-09-07T18:39:03+08:00`)

## Comparison

| Metric | rules | real (FIXTURE — not live API) |
| --- | --- | --- |
| answer_accuracy | 1.0000 | 1.0000 |
| exec_success_rate | 1.0000 | 1.0000 |
| repair_success_rate | n/a (no repair attempts in this split) | n/a (no repair attempts in this split) |
| block_rate | 1.0000 | 1.0000 |

## Labels

| Run | model/mode | llm_calls | not_real_api |
| --- | --- | --- | --- |
| rules | rules | none | true |
| real/fixture | mock-fixture | fixture | true |

## Honesty

- **Rules** scores are offline rules/heuristics — useful gate signal for gate+exec path.
- **Real/fixture** scores use `mock_llm_responses.json` — **`llm_calls=fixture` / `not_real_api=true`**. Never present as true model performance.
- Gold test set size left at n=12 (not expanded to 150–200).

## Artifacts

- `evals/reports/baseline_rules_test.json`
- `evals/reports/baseline_rules_3aeb37a.md`
- `evals/reports/baseline_real_fixture_test.json`
- `evals/reports/baseline_real_3aeb37a.md`
- `evals/reports/baseline_summary_3aeb37a.md`
