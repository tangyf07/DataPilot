"""DuckDB query engine (preferred backend)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from datapilot.query.seed import seed_demo_data


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    sql: str


class DuckDBEngine:
    def __init__(self, db_path: Path | str, auto_seed: bool = True) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        if auto_seed:
            self.ensure_seeded()

    def ensure_seeded(self) -> None:
        try:
            n = self.conn.execute("SELECT count(*) FROM ads_dau_daily").fetchone()[0]
            if n and n > 0:
                return
        except Exception:
            pass
        seed_demo_data(self.conn)

    def execute(self, sql: str) -> QueryResult:
        cur = self.conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return QueryResult(columns=cols, rows=rows, sql=sql)

    def close(self) -> None:
        self.conn.close()
