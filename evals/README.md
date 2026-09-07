# DataPilot evals

Gold-question harness for offline regression (DuckDB + SQLGuard mock/rules by default).

**Not** a full production judge. Scores are **heuristics**, not LLM-as-judge.

## Layout

```
evals/
  README.md
  schema.md / schema.json
  gold/train/gold.jsonl   # 28 samples (MVP)
  gold/test/gold.jsonl    # 12 samples
  fixtures/mock_llm_responses.json
  scripts/run_eval.py
```

Scale target later: ~150–200 gold; this skeleton starts at **40**.

## Honesty

- Retrieval is **hardcoded keyword docs** (`MockGameStreamRetriever`), **not** vector RAG / embeddings.
- SQL execution success ≠ analytically correct answer (口径 / 时间窗 still need human review).
- `answer_accuracy` is pattern + optional result checks — **not** semantic equivalence.
- `--mode real` without `OPENAI_API_KEY` uses **fixtures** (or SKIP if none); scores are not invented.

## Metrics

| Key | Chinese | Definition |
|-----|---------|------------|
| `answer_accuracy` | 答案正确率 | Among `expect_gate=EXECUTE`: generated SQL matches **all** `gold_sql_patterns` **and** optional `gold_answer_check` (rows/columns). Heuristic. |
| `exec_success_rate` | SQL执行成功率 | Among EXECUTE items: gate ALLOW’d and query ran without error. |
| `repair_success_rate` | 修复成功率 | Among EXECUTE items whose **first attempt failed and retried**, fraction that succeeded after retry. `null` if no retries in the run. |
| `block_rate` | 危险拦截率 | Among `expect_gate=BLOCK`: fraction where the gate blocked (or REQUIRE_APPROVAL) the provided `gold_sql`. |

Schema details: [schema.md](./schema.md).

## How to run

From repo root (venv with DataPilot installed):

```bash
# rules / offline default
python evals/scripts/run_eval.py --mode rules --split test

# train split
python evals/scripts/run_eval.py --mode rules --split train

# all gold
python evals/scripts/run_eval.py --mode rules --split all

# real: uses OPENAI_API_KEY if set; else mock fixtures under evals/fixtures/
python evals/scripts/run_eval.py --mode real --split test

# side-by-side compare (one process)
python evals/scripts/run_eval.py --compare rules,real --split test --quiet-items

# smoke: tiny subset
python evals/scripts/run_eval.py --mode rules --split test --limit 3 --quiet-items
```

Exit code **0** on successful run (including SKIP of real when documented). Exit **2** on bad args.

### Compare without `--compare`

Run twice and diff JSON summaries:

```bash
python evals/scripts/run_eval.py --mode rules --split test --quiet-items > /tmp/rules.json
python evals/scripts/run_eval.py --mode real --split test --quiet-items > /tmp/real.json
```

`--compare rules,real` prints a small side-by-side `compare` table of the four rates.

## Sample JSON summary shape

```json
{
  "mode": "rules",
  "split": "test",
  "n_total": 12,
  "n_execute": 10,
  "n_block": 2,
  "answer_accuracy": 0.9,
  "answer_accuracy_note": "heuristic: ...",
  "exec_success_rate": 1.0,
  "repair_success_rate": null,
  "repair_n": 0,
  "block_rate": 1.0,
  "counts": {
    "answer_ok": 9,
    "answer_scored": 10,
    "exec_ok": 10,
    "exec_scored": 10,
    "repair_ok": 0,
    "repair_scored": 0,
    "block_ok": 2,
    "block_scored": 2
  },
  "real_path": "rules",
  "items": []
}
```

## BLOCK items

Dangerous cases ship `gold_sql` and `expect_gate=BLOCK`. The runner checks the **mock gate** on that SQL (does not trust NL→SQL to invent DROP/TRUNCATE).
