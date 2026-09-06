"""Trace each pipeline step: model, prompt, SQL, gate, timings."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class StepTrace:
    name: str
    started_at: float
    ended_at: float | None = None
    duration_ms: float | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def finish(self, **detail: Any) -> None:
        self.ended_at = time.perf_counter()
        self.duration_ms = round((self.ended_at - self.started_at) * 1000, 3)
        self.detail.update(detail)


@dataclass
class RunTrace:
    run_id: str
    question: str
    started_at: str
    model: str | None = None
    prompt: str | None = None
    sql: str | None = None
    gate: dict[str, Any] | None = None
    steps: list[StepTrace] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def start_step(self, name: str) -> StepTrace:
        step = StepTrace(name=name, started_at=time.perf_counter())
        self.steps.append(step)
        return step

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "started_at": self.started_at,
            "model": self.model,
            "prompt": self.prompt,
            "sql": self.sql,
            "gate": self.gate,
            "steps": [
                {
                    "name": s.name,
                    "duration_ms": s.duration_ms,
                    "detail": s.detail,
                }
                for s in self.steps
            ],
            "meta": self.meta,
        }


class Tracer:
    def __init__(self, trace_dir: Path | str) -> None:
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def begin(self, question: str) -> RunTrace:
        return RunTrace(
            run_id=str(uuid.uuid4()),
            question=question,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def save(self, run: RunTrace) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self.trace_dir / f"run_{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(run.to_dict(), ensure_ascii=False) + "\n")
        # also per-run file for easy CLI pointer
        single = self.trace_dir / f"run_{run.run_id}.json"
        single.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return single
