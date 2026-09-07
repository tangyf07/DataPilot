"""CLI entry: python -m datapilot "..." | demo | g7."""

from __future__ import annotations

import argparse
import os
import sys

from datapilot.config import DEFAULT_DORIS_URL, Settings, get_settings
from datapilot.pipeline import Pipeline, run_question


DEMO_QUESTIONS = [
    "昨天DAU多少？",
    "近7天留存怎么样？",
    "最近ARPU和付费率？",
]

G7_QUESTIONS = [
    "昨天/最近 DAU",
    "付费率",
]


def _print_result(result) -> None:
    print("=" * 60)
    print(f"Question : {result.question}")
    print(
        f"Intent   : {result.intent.name} metric={result.intent.metric} "
        f"time={result.intent.time_hint} server_id={result.intent.server_id} "
        f"conf={result.intent.confidence}"
    )
    print(f"Backend  : {getattr(result, 'query_backend', '?')} path={getattr(result, 'query_path', '?')}")
    print("RAG docs :")
    for d in result.docs:
        print(f"  - [{d.score:.1f}] {d.title}")
    if result.sql_gen:
        print(f"Model    : {result.sql_gen.model} ({result.sql_gen.mode})")
        print(f"SQL      : {result.sql_gen.sql}")
    if result.gate:
        dp = f" datapilot={result.gate.datapilot}" if result.gate.datapilot else ""
        rs = f" risk_score={result.gate.risk_score}" if result.gate.risk_score is not None else ""
        ex = f" executed={result.gate.executed}" if result.gate.executed else ""
        print(
            f"Gate     : {result.gate.action}{dp}{rs}{ex} allowed={result.gate.allowed} "
            f"rule={result.gate.rule_id} — {result.gate.reason}"
        )
    if result.retries:
        print(f"Retries  : {len(result.retries)} (attempts={result.attempts})")
        for r in result.retries:
            print(f"  - attempt {r.get('attempt')} @ {r.get('stage')}: {r.get('reason')}")
    if result.blocked:
        print("Status   : BLOCKED by SQLGuard")
    if result.error:
        print(f"Error    : {result.error}")
    if result.query is not None:
        print(f"Rows     : {len(result.query.rows)} cols={result.query.columns}")
    if result.report:
        print("-" * 60)
        print("Table:")
        print(result.report.table_text)
        print("-" * 60)
        print(f"Conclusion: {result.report.conclusion}")
        if result.report.chart_path:
            print(f"Chart    : {result.report.chart_path}")
    print(f"Trace    : {result.trace_path}")
    print("=" * 60)


def _settings_for_g7() -> Settings:
    """Force Doris backend for G7 demo; default URL if unset."""
    os.environ.setdefault("DATAPILOT_QUERY_BACKEND", "doris")
    if not os.environ.get("DATAPILOT_DORIS_URL"):
        os.environ["DATAPILOT_DORIS_URL"] = DEFAULT_DORIS_URL
    os.environ.setdefault("DATAPILOT_GUARD_MODE", "write_gate")
    os.environ.setdefault("DATAPILOT_LLM_MODE", "mock")
    return get_settings()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datapilot", description="DataPilot ChatBI agent loop")
    parser.add_argument("question", nargs="?", help="Natural language question, or 'demo' / 'g7'")
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--demo", action="store_true", help="Run demo questions")
    parser.add_argument("--g7", action="store_true", help="G7: ChatBI → SQLGuard → Doris ADS")
    args = parser.parse_args(argv)

    q = args.question
    if q == "g7" or args.g7:
        settings = _settings_for_g7()
        pipe = Pipeline(settings=settings)
        print(
            f"DataPilot G7 (backend={pipe.backend}, guard={settings.guard_mode}, "
            f"doris={settings.doris_url}, llm={settings.llm_mode})"
        )
        print("Path: ChatBI → SQLGuard 1.1 → GameStream Doris ADS (DAU + pay_rate)")
        rc = 0
        for question in G7_QUESTIONS:
            result = pipe.run(question)
            _print_result(result)
            if result.blocked or result.error:
                rc = 1
        return rc

    if q == "demo" or args.demo:
        settings = get_settings()
        pipe = Pipeline(settings=settings)
        print(
            f"DataPilot demo (llm_mode={settings.llm_mode}, "
            f"guard={settings.guard_mode}, backend={pipe.backend}, db={settings.db_path})"
        )
        for question in DEMO_QUESTIONS:
            _print_result(pipe.run(question))
        return 0

    if not q:
        parser.print_help()
        return 2

    if args.extra:
        q = " ".join([q, *args.extra])

    result = run_question(q)
    _print_result(result)
    return 0 if not result.blocked and not result.error else 1


if __name__ == "__main__":
    raise SystemExit(main())
