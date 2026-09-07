"""Fast smoke for gold eval harness (no network)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUN_EVAL = REPO / "evals" / "scripts" / "run_eval.py"


def test_eval_helpers_importable() -> None:
    """Import metric helpers from run_eval without running full pipeline."""
    sys.path.insert(0, str(RUN_EVAL.parent))
    import run_eval as reval  # noqa: E402

    assert reval.sql_matches_patterns(
        "SELECT dau FROM ads_dau_di WHERE dt = current_date - INTERVAL 1 DAY",
        ["ads_dau_di", r"(?i)INTERVAL\s*1\s*DAY"],
    )
    assert not reval.sql_matches_patterns("SELECT 1", ["ads_dau_di"])
    assert reval.check_answer_result(["dt", "dau"], 2, {"expect_rows_min": 1, "expect_columns": ["dau"]})
    assert not reval.check_answer_result(["dt"], 0, {"expect_columns": ["dau"]})


def test_gold_files_exist_and_count() -> None:
    train = (REPO / "evals" / "gold" / "train" / "gold.jsonl").read_text(encoding="utf-8").strip().splitlines()
    test = (REPO / "evals" / "gold" / "test" / "gold.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(train) == 28
    assert len(test) == 12
    for line in train + test:
        rec = json.loads(line)
        assert rec["id"] and rec["expect_gate"] in ("EXECUTE", "BLOCK")
        assert "tags" in rec


def test_run_eval_script_smoke() -> None:
    """Run script on tiny subset; must exit 0 and print JSON with four metric keys."""
    proc = subprocess.run(
        [
            sys.executable,
            str(RUN_EVAL),
            "--mode",
            "rules",
            "--split",
            "test",
            "--limit",
            "4",
            "--quiet-items",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
        env={**dict(**__import__("os").environ), "DATAPILOT_LLM_MODE": "rules", "DATAPILOT_QUERY_BACKEND": "duckdb"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(proc.stdout)
    for key in (
        "answer_accuracy",
        "exec_success_rate",
        "repair_success_rate",
        "block_rate",
    ):
        assert key in data
    assert data["mode"] == "rules"
    assert data["n_total"] == 4
