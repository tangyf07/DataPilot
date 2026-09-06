"""CLI entry: python -m datapilot "..." | python -m datapilot demo."""

from __future__ import annotations

import argparse
import sys

from datapilot.config import get_settings
from datapilot.pipeline import Pipeline, run_question


DEMO_QUESTIONS = [
    "昨天DAU多少？",
    "近7天留存怎么样？",
    "最近ARPU和付费率？",
]


def _print_result(result) -> None:
    print("=" * 60)
    print(f"Question : {result.question}")
    print(
        f"Intent   : {result.intent.name} metric={result.intent.metric} "
        f"time={result.intent.time_hint} conf={result.intent.confidence}"
    )
    print("RAG docs :")
    for d in result.docs:
        print(f"  - [{d.score:.1f}] {d.title}")
    if result.sql_gen:
        print(f"Model    : {result.sql_gen.model} ({result.sql_gen.mode})")
        print(f"SQL      : {result.sql_gen.sql}")
    if result.gate:
        dp = f" datapilot={result.gate.datapilot}" if result.gate.datapilot else ""
        rs = f" risk_score={result.gate.risk_score}" if result.gate.risk_score is not None else ""
        print(
            f"Gate     : {result.gate.action}{dp}{rs} allowed={result.gate.allowed} "
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datapilot", description="DataPilot ChatBI agent loop")
    parser.add_argument("question", nargs="?", help="Natural language question")
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--demo", action="store_true", help="Run demo questions")
    args = parser.parse_args(argv)

    q = args.question
    if q == "demo" or args.demo:
        settings = get_settings()
        pipe = Pipeline(settings=settings)
        print(
            f"DataPilot demo (llm_mode={settings.llm_mode}, "
            f"guard={settings.guard_mode}, db={settings.db_path})"
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
