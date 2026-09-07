# Gold question schema

Each line in `gold/{train,test}/gold.jsonl` is one JSON object.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Stable sample id (`g001` …) |
| `split` | `"train"` \| `"test"` | yes | Must match the file under `gold/<split>/` |
| `question` | string | yes | Natural-language question (or prose describing a dangerous SQL case) |
| `metric_id` | string | yes | Expected metric family: `dau` \| `pay_rate` \| `retention` \| `arpu` (etc.) |
| `time_hint` | string | yes | `yesterday` \| `today` \| `last_7_days` \| `latest` |
| `gold_sql` | string | for `BLOCK` | Exact SQL fed to the gate for dangerous cases |
| `gold_sql_patterns` | string[] | for `EXECUTE` | Substring or regex patterns; SQL must match **all** (MVP) |
| `expect_gate` | `"EXECUTE"` \| `"BLOCK"` | yes | Expected SQLGuard outcome |
| `gold_answer_check` | object \| null | no | Optional result checks after ALLOW+exec |
| `tags` | string[] | yes | Free-form tags (`dau`, `block`, `test`, …) |

## `gold_answer_check` (optional)

```json
{
  "expect_rows_min": 0,
  "expect_columns": ["dau", "dt"]
}
```

- `expect_rows_min`: minimum row count (heuristic; seed may be empty for some dates)
- `expect_columns`: column names that should appear (case-insensitive)

## Pattern matching

Each entry in `gold_sql_patterns` is tried as a **regex** (`re.search`). If the string has no regex metacharacters beyond simple literals, it still works as a substring match. All patterns must match for the SQL-pattern half of `answer_accuracy`.

## Gate semantics

- **EXECUTE**: run the offline pipeline on `question`; expect gate ALLOW / not blocked; score SQL + optional result checks.
- **BLOCK**: do **not** rely on NL→SQL; check `gold_sql` directly with the mock/local gate. Counted toward `block_rate`.

## Honesty

Retrieval is **keyword docs**, not vector RAG. Metrics are heuristics — not an LLM judge.
