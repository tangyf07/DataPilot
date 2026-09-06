"""Natural-language conclusion + simple table / optional chart."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datapilot.intent import Intent


@dataclass
class Report:
    conclusion: str
    table_text: str
    chart_path: str | None = None


def _fmt_table(columns: list[str], rows: list[tuple[Any, ...]], max_rows: int = 20) -> str:
    if not columns:
        return "(empty)"
    show = rows[:max_rows]
    widths = [len(c) for c in columns]
    str_rows = []
    for r in show:
        cells = ["" if v is None else str(v) for v in r]
        str_rows.append(cells)
        for i, c in enumerate(cells):
            widths[i] = max(widths[i], len(c))
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    sep = "-+-".join("-" * w for w in widths)
    body = [" | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) for r in str_rows]
    extra = f"\n... ({len(rows) - max_rows} more rows)" if len(rows) > max_rows else ""
    return "\n".join([header, sep, *body]) + extra


def _nl(intent: Intent, columns: list[str], rows: list[tuple[Any, ...]], ok: bool) -> str:
    if not ok or not rows:
        return f"未能从结果中得到有效数据（问题：{intent.raw}）。请检查时间范围或指标。"
    metric = intent.metric or "指标"
    first = rows[0]
    # try find metric-like column
    label = None
    value = None
    for i, c in enumerate(columns):
        cl = c.lower()
        if metric and metric in cl:
            label, value = c, first[i]
            break
    if label is None and len(columns) >= 2:
        label, value = columns[-1], first[-1]
    dt = None
    for i, c in enumerate(columns):
        if c.lower() in ("dt", "date", "day"):
            dt = first[i]
            break
    time_part = f"（日期 {dt}）" if dt is not None else ""
    if len(rows) == 1:
        return f"根据查询，{metric}{time_part}为 **{value}**（字段 {label}）。共返回 {len(rows)} 行。"
    # trend hint
    return (
        f"根据查询，已返回近 {len(rows)} 天的 {metric} 数据{time_part}。"
        f"首行 {label}={value}；详见下表。"
    )


def _maybe_chart(columns: list[str], rows: list[tuple[Any, ...]], out_dir: Path) -> str | None:
    if len(rows) < 2 or len(columns) < 2:
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    try:
        x = [r[0] for r in rows]
        # pick last numeric-ish col
        y_idx = len(columns) - 1
        for i in range(len(columns) - 1, 0, -1):
            if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows):
                y_idx = i
                break
        y = [r[y_idx] for r in rows]
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(x, y, marker="o")
        ax.set_xlabel(columns[0])
        ax.set_ylabel(columns[y_idx])
        ax.set_title("DataPilot chart")
        fig.autofmt_xdate()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "last_chart.png"
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        return str(path)
    except Exception:
        return None


def build_report(
    intent: Intent,
    columns: list[str],
    rows: list[tuple[Any, ...]],
    validation_ok: bool,
    chart_dir: Path | None = None,
) -> Report:
    table = _fmt_table(columns, rows)
    conclusion = _nl(intent, columns, rows, validation_ok)
    chart = None
    if chart_dir is not None:
        chart = _maybe_chart(columns, rows, chart_dir)
    return Report(conclusion=conclusion, table_text=table, chart_path=chart)
