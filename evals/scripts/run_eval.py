#!/usr/bin/env python3
"""DataPilot gold eval runner — four heuristic metrics (offline DuckDB + rules by default).

Metrics (printed as JSON summary):
  1. answer_accuracy   — SQL matches gold patterns AND/OR result validation (heuristic, not LLM-judge)
  2. exec_success_rate — among expect_gate=EXECUTE that were ALLOW'd, query ran without error
  3. repair_success_rate — among first-attempt failures that retried, fraction succeeded on retry
  4. block_rate        — among expect_gate=BLOCK, fraction blocked by gate

Honesty: retrieval is keyword docs, not vector RAG. Scores are heuristics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Repo root on sys.path for `datapilot` when run as a script
_EVALS = Path(__file__).resolve().parents[1]
_REPO = _EVALS.parent
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def load_gold(split: str) -> list[dict[str, Any]]:
    splits = ["train", "test"] if split == "all" else [split]
    rows: list[dict[str, Any]] = []
    for sp in splits:
        path = _EVALS / "gold" / sp / "gold.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"missing gold file: {path}")
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rows.append(json.loads(line))
    return rows


def load_mock_fixtures() -> dict[str, Any]:
    path = _EVALS / "fixtures" / "mock_llm_responses.json"
    if not path.exists():
        return {"by_id": {}, "default_sql": None}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def sql_matches_patterns(sql: str | None, patterns: list[str] | None) -> bool:
    if not patterns:
        return bool(sql)
    if not sql:
        return False
    for pat in patterns:
        try:
            if re.search(pat, sql) is None:
                return False
        except re.error:
            if pat not in sql:
                return False
    return True


def check_answer_result(
    columns: list[str] | None,
    row_count: int,
    check: dict[str, Any] | None,
) -> bool:
    if not check:
        return True
    if "expect_rows_min" in check and row_count < int(check["expect_rows_min"]):
        return False
    expect_cols = check.get("expect_columns") or []
    if expect_cols:
        lower = {c.lower() for c in (columns or [])}
        for col in expect_cols:
            if col.lower() not in lower:
                return False
    return True


@dataclass
class ItemResult:
    id: str
    expect_gate: str
    mode: str
    skipped: bool = False
    skip_reason: str | None = None
    blocked: bool | None = None
    gate_action: str | None = None
    sql: str | None = None
    sql_pattern_ok: bool | None = None
    result_ok: bool | None = None
    answer_ok: bool | None = None
    exec_ok: bool | None = None
    retried: bool = False
    repair_ok: bool | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _make_settings(mode: str, work: Path):
    from datapilot.config import Settings

    return Settings(
        llm_mode=mode,
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        db_path=work / "eval.duckdb",
        guard_mode="mock",
        trace_dir=work / "traces",
        project_root=work,
        guard_url=None,
        guard_catalog=None,
        guard_policy=None,
        query_backend="duckdb",
        doris_url=None,
    )


def _fixture_sql(fixtures: dict[str, Any], gold_id: str) -> str | None:
    by_id = fixtures.get("by_id") or {}
    return by_id.get(gold_id)


def _patch_real_with_fixtures(fixtures: dict[str, Any], gold_id: str, monkey_sql: str | None):
    """Return a generate_sql wrapper that uses fixture SQL when no API key."""
    from datapilot.sql.generator import SQLGeneration, generate_sql as real_generate

    def wrapped(intent, docs, settings, feedback=None, *, previous_sql=None):
        key = os.getenv("OPENAI_API_KEY")
        if key:
            return real_generate(
                intent, docs, settings, feedback=feedback, previous_sql=previous_sql
            )
        sql = monkey_sql or _fixture_sql(fixtures, gold_id)
        if not sql:
            return SQLGeneration(
                sql="",
                model="fixture-missing",
                prompt="[eval] no fixture and no OPENAI_API_KEY",
                mode="degraded",
                degraded_from="real",
                real_model_error="no fixture / no OPENAI_API_KEY",
            )
        return SQLGeneration(
            sql=sql,
            model="mock-fixture",
            prompt=f"[eval fixture] id={gold_id}",
            mode="real",  # fixture stands in for real offline; documented as mock path
            degraded_from=None,
            real_model_error=None,
        )

    return wrapped


def eval_block_item(rec: dict[str, Any]) -> ItemResult:
    from datapilot.guard.mock import MockSQLGuardClient

    gold_sql = rec.get("gold_sql") or ""
    gate = MockSQLGuardClient().check(gold_sql)
    blocked = not gate.allowed or gate.action == "BLOCK"
    # REQUIRE_APPROVAL also counts as not EXECUTE for dangerous writes
    if gate.action in ("BLOCK", "REQUIRE_APPROVAL"):
        blocked = True
    return ItemResult(
        id=rec["id"],
        expect_gate="BLOCK",
        mode="gate-only",
        blocked=blocked,
        gate_action=gate.action,
        sql=gold_sql,
        answer_ok=None,
        exec_ok=None,
        details={"reason": gate.reason, "rule_id": gate.rule_id},
    )


def eval_execute_item(
    rec: dict[str, Any],
    *,
    mode: str,
    settings,
    fixtures: dict[str, Any],
    use_fixture_for_real: bool,
) -> ItemResult:
    from datapilot import pipeline as pipeline_mod
    from datapilot.pipeline import Pipeline
    from datapilot.sql.generator import generate_sql as real_generate

    ir = ItemResult(id=rec["id"], expect_gate="EXECUTE", mode=mode)
    orig = pipeline_mod.generate_sql
    try:
        if mode == "real" and use_fixture_for_real:
            pipeline_mod.generate_sql = _patch_real_with_fixtures(fixtures, rec["id"], None)
        elif mode == "rules":
            # ensure rules path
            pass

        pipe = Pipeline(settings=settings)
        result = pipe.run(rec["question"])

        ir.blocked = bool(result.blocked)
        ir.gate_action = result.gate.action if result.gate else None
        ir.sql = result.sql_gen.sql if result.sql_gen else None
        ir.error = result.error
        ir.retried = bool(result.retries) or (result.attempts or 1) > 1

        patterns = rec.get("gold_sql_patterns") or []
        ir.sql_pattern_ok = sql_matches_patterns(ir.sql, patterns)

        cols = list(result.query.columns) if result.query else []
        row_count = (
            result.validation.row_count
            if result.validation
            else (len(result.query.rows) if result.query else 0)
        )
        ir.result_ok = check_answer_result(cols, row_count, rec.get("gold_answer_check"))

        # Heuristic answer_accuracy: patterns OK, and if checks present they pass;
        # also require not blocked for EXECUTE items.
        if ir.blocked:
            ir.answer_ok = False
        else:
            ir.answer_ok = bool(ir.sql_pattern_ok) and bool(ir.result_ok)

        # exec_success: ALLOW and query produced without error
        if ir.blocked:
            ir.exec_ok = False
        else:
            ir.exec_ok = (
                result.query is not None
                and result.error is None
                and (result.gate is None or result.gate.allowed)
            )

        # repair: first attempt failed, then retry happened
        if ir.retried:
            # success on retry = final not blocked and exec_ok
            ir.repair_ok = bool(ir.exec_ok) and not ir.blocked
        else:
            ir.repair_ok = None

        ir.details = {
            "attempts": result.attempts,
            "retries": result.retries,
            "llm_mode": result.sql_gen.mode if result.sql_gen else None,
            "row_count": row_count,
            "columns": cols,
            "metric_intent": result.intent.metric if result.intent else None,
            "time_hint_intent": result.intent.time_hint if result.intent else None,
        }
    except Exception as exc:  # noqa: BLE001
        ir.error = str(exc)
        ir.answer_ok = False
        ir.exec_ok = False
        ir.details["exception"] = type(exc).__name__
    finally:
        pipeline_mod.generate_sql = orig
    return ir


def aggregate(items: list[ItemResult], *, mode: str, split: str, skipped_real: bool = False) -> dict[str, Any]:
    execute_items = [i for i in items if i.expect_gate == "EXECUTE" and not i.skipped]
    block_items = [i for i in items if i.expect_gate == "BLOCK" and not i.skipped]

    answer_scored = [i for i in execute_items if i.answer_ok is not None]
    answer_ok_n = sum(1 for i in answer_scored if i.answer_ok)
    answer_accuracy = (answer_ok_n / len(answer_scored)) if answer_scored else None

    exec_scored = [i for i in execute_items if i.exec_ok is not None]
    exec_ok_n = sum(1 for i in exec_scored if i.exec_ok)
    exec_success_rate = (exec_ok_n / len(exec_scored)) if exec_scored else None

    repair_pool = [i for i in execute_items if i.retried and i.repair_ok is not None]
    repair_ok_n = sum(1 for i in repair_pool if i.repair_ok)
    repair_success_rate = (repair_ok_n / len(repair_pool)) if repair_pool else None

    block_ok_n = sum(1 for i in block_items if i.blocked)
    block_rate = (block_ok_n / len(block_items)) if block_items else None

    return {
        "mode": mode,
        "split": split,
        "n_total": len(items),
        "n_execute": len(execute_items),
        "n_block": len(block_items),
        "n_skipped": sum(1 for i in items if i.skipped),
        "skipped_real": skipped_real,
        "answer_accuracy": answer_accuracy,
        "answer_accuracy_note": "heuristic: all gold_sql_patterns match AND gold_answer_check (if any); not LLM-judge",
        "exec_success_rate": exec_success_rate,
        "repair_success_rate": repair_success_rate,
        "repair_n": len(repair_pool),
        "block_rate": block_rate,
        "counts": {
            "answer_ok": answer_ok_n,
            "answer_scored": len(answer_scored),
            "exec_ok": exec_ok_n,
            "exec_scored": len(exec_scored),
            "repair_ok": repair_ok_n,
            "repair_scored": len(repair_pool),
            "block_ok": block_ok_n,
            "block_scored": len(block_items),
        },
        "items": [asdict(i) for i in items],
    }


def run_one_mode(mode: str, split: str, *, limit: int | None = None) -> dict[str, Any]:
    gold = load_gold(split)
    if limit is not None:
        gold = gold[:limit]

    has_key = bool(os.getenv("OPENAI_API_KEY"))
    fixtures = load_mock_fixtures()

    if mode == "real" and not has_key:
        # Prefer fixtures; if fixture file empty of usable SQL, SKIP clearly
        by_id = fixtures.get("by_id") or {}
        if not by_id and not fixtures.get("default_sql"):
            skipped = [
                ItemResult(
                    id=r["id"],
                    expect_gate=r["expect_gate"],
                    mode="real",
                    skipped=True,
                    skip_reason="SKIP: --mode real without OPENAI_API_KEY and no mock fixtures",
                )
                for r in gold
            ]
            return aggregate(skipped, mode="real", split=split, skipped_real=True)
        use_fixture = True
    else:
        use_fixture = False

    work = Path(tempfile.mkdtemp(prefix="datapilot_eval_"))
    try:
        settings = _make_settings("rules" if mode == "rules" else "real", work)
        # For real+fixture we still set llm_mode=real but patch generate_sql
        if mode == "real" and use_fixture:
            settings.llm_mode = "real"
            settings.openai_api_key = None

        results: list[ItemResult] = []
        for rec in gold:
            if rec.get("expect_gate") == "BLOCK":
                results.append(eval_block_item(rec))
            elif mode == "real" and use_fixture and not _fixture_sql(fixtures, rec["id"]):
                results.append(
                    ItemResult(
                        id=rec["id"],
                        expect_gate=rec["expect_gate"],
                        mode="real",
                        skipped=True,
                        skip_reason="SKIP: no fixture for id and no OPENAI_API_KEY",
                    )
                )
            else:
                results.append(
                    eval_execute_item(
                        rec,
                        mode=mode,
                        settings=settings,
                        fixtures=fixtures,
                        use_fixture_for_real=use_fixture,
                    )
                )
        summary = aggregate(results, mode=mode, split=split, skipped_real=False)
        if use_fixture:
            summary["real_path"] = "mock_fixture"
            summary["llm_calls"] = "fixture"
            summary["not_real_api"] = True
            summary["model"] = "mock-fixture"
            summary["note"] = (
                "OPENAI_API_KEY missing: used evals/fixtures/mock_llm_responses.json "
                "(not a live model). Do not invent scores beyond fixture coverage. "
                "llm_calls=fixture / not_real_api=true — NOT true model performance."
            )
        elif mode == "real":
            base_url = (os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
            model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
            provider = "deepseek" if "deepseek" in base_url.lower() else "openai_compatible"
            degraded_items = [
                i.id
                for i in results
                if (i.details or {}).get("llm_mode") == "degraded"
            ]
            retried_items = [i.id for i in results if i.retried]
            failed_ids = [
                i.id
                for i in results
                if not i.skipped and i.expect_gate == "EXECUTE" and i.answer_ok is False
            ]
            summary["real_path"] = "openai"
            summary["llm_calls"] = "live"
            summary["not_real_api"] = False
            summary["model"] = model
            summary["provider"] = provider
            summary["base_url"] = base_url
            summary["openai_api_key_set"] = True
            summary["failed_item_ids"] = failed_ids
            summary["degraded_items"] = degraded_items
            summary["degraded_count"] = len(degraded_items)
            summary["retry_stats"] = {
                "n_retried": len(retried_items),
                "retried_items": retried_items,
                "repair_success_rate": summary.get("repair_success_rate"),
                "repair_n": summary.get("repair_n"),
            }
            summary["note"] = (
                f"live {provider} OpenAI-compatible API "
                f"(not_real_api=false, llm_calls=live, model={model}). Not fixture/mock."
            )
        else:
            summary["real_path"] = "rules"
        return summary
    finally:
        shutil.rmtree(work, ignore_errors=True)


def compare_summaries(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [
        "answer_accuracy",
        "exec_success_rate",
        "repair_success_rate",
        "block_rate",
    ]
    table = []
    for m in metrics:
        row = {"metric": m}
        for s in summaries:
            row[s["mode"]] = s.get(m)
        table.append(row)
    return {"compare": table, "runs": [{k: s[k] for k in s if k != "items"} for s in summaries]}



def _summary_md(out: dict[str, Any]) -> str:
    """Minimal markdown for a single-mode or compare JSON payload."""
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    if "compare" in out:
        lines.append("# DataPilot eval compare")
        lines.append("")
        lines.append(f"- timestamp: `{ts}`")
        lines.append("")
        for row in out.get("compare") or []:
            metric = row.get("metric")
            vals = {k: v for k, v in row.items() if k != "metric"}
            lines.append(f"- **{metric}**: {vals}")
        lines.append("")
        return "\n".join(lines) + "\n"

    mode = out.get("mode", "?")
    real_path = out.get("real_path", mode)
    lines.append(f"# DataPilot baseline — mode=`{mode}` path=`{real_path}`")
    lines.append("")
    lines.append(f"- timestamp: `{ts}`")
    lines.append(f"- mode: `{mode}`")
    lines.append(f"- real_path: `{real_path}`")
    lines.append(f"- split: `{out.get('split')}`")
    lines.append(f"- n_total: `{out.get('n_total')}`")
    for m in ("answer_accuracy", "exec_success_rate", "repair_success_rate", "block_rate"):
        lines.append(f"- **{m}**: `{out.get(m)}`")
    if out.get("note"):
        lines.append("")
        lines.append(f"> Honesty: {out['note']}")
    if out.get("model"):
        lines.append(f"- model: `{out.get('model')}`")
    if out.get("provider"):
        lines.append(f"- provider: `{out.get('provider')}`")
    if out.get("base_url"):
        lines.append(f"- base_url: `{out.get('base_url')}`")
    if "not_real_api" in out:
        lines.append(f"- not_real_api: `{out.get('not_real_api')}`")
    if out.get("llm_calls"):
        lines.append(f"- llm_calls: `{out.get('llm_calls')}`")
    if out.get("degraded_count") is not None:
        lines.append(f"- degraded_count: `{out.get('degraded_count')}`")
    if out.get("failed_item_ids"):
        lines.append(f"- failed_item_ids: `{out.get('failed_item_ids')}`")
    if real_path == "mock_fixture" or out.get("llm_calls") == "fixture":
        lines.append("")
        lines.append("> **Fixture run — not live model performance.** `llm_calls=fixture` / `not_real_api=true`")
    elif out.get("llm_calls") == "live" and out.get("not_real_api") is False:
        lines.append("")
        lines.append("> **Live API run.** `llm_calls=live` / `not_real_api=false`")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="DataPilot gold eval (four heuristic metrics)")
    p.add_argument("--mode", default="rules", help="rules|real  or compare: rules,real")
    p.add_argument("--split", default="test", choices=["test", "train", "all"])
    p.add_argument("--limit", type=int, default=None, help="optional cap on gold rows (smoke)")
    p.add_argument("--compare", default=None, help="alias: comma modes e.g. rules,real")
    p.add_argument("--quiet-items", action="store_true", help="omit per-item details from JSON")
    p.add_argument("--out", type=Path, default=None, help="write JSON summary to PATH")
    p.add_argument("--report-md", type=Path, default=None, help="write markdown summary to PATH")
    args = p.parse_args(argv)

    modes_raw = args.compare or args.mode
    modes = [m.strip() for m in modes_raw.split(",") if m.strip()]
    for m in modes:
        if m not in ("rules", "real"):
            print(json.dumps({"error": f"unsupported mode: {m}"}), flush=True)
            return 2

    summaries = [run_one_mode(m, args.split, limit=args.limit) for m in modes]

    if len(summaries) == 1:
        out = summaries[0]
        if args.quiet_items:
            out = {k: v for k, v in out.items() if k != "items"}
    else:
        out = compare_summaries(summaries)
        if not args.quiet_items:
            out["items_by_mode"] = {s["mode"]: s.get("items") for s in summaries}

    payload = json.dumps(out, ensure_ascii=False, indent=2)
    print(payload)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    if args.report_md:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(_summary_md(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
