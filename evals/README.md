# DataPilot evals (skeleton)

Light gold-question harness scaffold. **Not** a full regression suite yet.

## Files

- `gold_questions.example.jsonl` — example NL questions with expected metric / table hints.

## Honest notes

- Retrieval today is **hardcoded keyword docs**, not vector RAG.
- SQL execution success ≠ correct analytical answer.
- LLM modes: `real` | `rules` | `degraded` (see root README).

## Next (follow-up)

Wire a runner that loads JSONL, runs the offline pipeline in `rules` mode, and checks table/metric presence — without claiming answer correctness.
