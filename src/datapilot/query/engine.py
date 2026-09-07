"""Query engines: DuckDB (offline) and Doris/MySQL (GameStream ADS)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import duckdb

from datapilot.query.seed import seed_demo_data


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    sql: str
    backend: str = "duckdb"
    path: str = "direct"  # direct | sqlguard_execute | sqlguard_check_then_pymysql


class DuckDBEngine:
    def __init__(self, db_path: Path | str, auto_seed: bool = True) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        if auto_seed:
            self.ensure_seeded()

    def ensure_seeded(self) -> None:
        need_seed = False
        try:
            n = self.conn.execute("SELECT count(*) FROM ads_dau_di").fetchone()[0]
            if not n:
                need_seed = True
        except Exception:
            need_seed = True
        if not need_seed:
            return
        seed_demo_data(self.conn)

    def execute(self, sql: str) -> QueryResult:
        cur = self.conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        return QueryResult(columns=cols, rows=rows, sql=sql, backend="duckdb", path="direct")

    def close(self) -> None:
        self.conn.close()


def _parse_mysql_url(url: str) -> dict[str, Any]:
    """Parse mysql://user:pass@host:port/db into pymysql connect kwargs."""
    parsed = urlparse(url)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise ValueError(f"unsupported Doris/MySQL URL scheme: {parsed.scheme!r}")
    database = (parsed.path or "/").lstrip("/") or "ads"
    password = unquote(parsed.password) if parsed.password else ""
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": int(parsed.port or 9030),
        "user": unquote(parsed.username) if parsed.username else "root",
        "password": password,
        "database": database,
        "charset": "utf8mb4",
        "connect_timeout": 5,
    }


class DorisEngine:
    """GameStream Doris FE via MySQL protocol (pymysql)."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._params = _parse_mysql_url(database_url)

    def execute(self, sql: str) -> QueryResult:
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Doris backend requires pymysql. Install with: pip install 'datapilot[doris]' "
                "or pip install pymysql"
            ) from exc
        conn = pymysql.connect(**self._params)
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows_raw = cur.fetchall()
                cols = [d[0] for d in cur.description] if cur.description else []
            rows = [tuple(r) for r in rows_raw]
            return QueryResult(
                columns=cols,
                rows=rows,
                sql=sql,
                backend="doris",
                path="direct",
            )
        finally:
            conn.close()

    def close(self) -> None:
        return


def build_engine(
    backend: str,
    *,
    db_path: Path | str | None = None,
    doris_url: str | None = None,
    auto_seed: bool = True,
) -> DuckDBEngine | DorisEngine:
    if backend == "doris":
        if not doris_url:
            raise ValueError("doris backend requires DATAPILOT_DORIS_URL")
        return DorisEngine(doris_url)
    return DuckDBEngine(db_path or Path("data/datapilot.duckdb"), auto_seed=auto_seed)



def columns_from_select(sql: str) -> list[str] | None:
    """Best-effort column names from a simple SELECT list (no nested parens)."""
    import re

    m = re.search(r"(?is)\bSELECT\s+(.*?)\s+FROM\b", sql.strip())
    if not m:
        return None
    raw = m.group(1).strip()
    if raw == "*" or not raw:
        return None
    cols: list[str] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        # alias: expr AS name / expr name
        am = re.search(r"(?i)\bas\s+([A-Za-z_][\w$]*)\s*$", part)
        if am:
            cols.append(am.group(1))
            continue
        tokens = part.split()
        if len(tokens) >= 2 and re.match(r"^[A-Za-z_][\w$]*$", tokens[-1]) and tokens[-2].lower() != "as":
            # bare alias after expression
            if "." in tokens[0] or "(" in part:
                cols.append(tokens[-1])
                continue
        # table.col or col
        leaf = tokens[-1]
        if "." in leaf:
            leaf = leaf.split(".")[-1]
        leaf = leaf.strip("`\"[]")
        if re.match(r"^[A-Za-z_][\w$]*$", leaf):
            cols.append(leaf)
        else:
            cols.append(f"c{len(cols)}")
    return cols or None


def query_result_from_gate_rows(
    sql: str,
    rows: list[Any] | None,
    columns: list[str] | None = None,
    *,
    path: str = "sqlguard_execute",
) -> QueryResult:
    """Map SQLGuard execute payload rows → QueryResult."""
    norm: list[tuple[Any, ...]] = []
    if rows:
        for r in rows:
            if isinstance(r, dict):
                if columns is None:
                    columns = list(r.keys())
                assert columns is not None
                norm.append(tuple(r.get(c) for c in columns))
            elif isinstance(r, (list, tuple)):
                norm.append(tuple(r))
            else:
                norm.append((r,))
    cols = list(columns) if columns else None
    if not cols:
        cols = columns_from_select(sql)
    if not cols:
        cols = [f"c{i}" for i in range(len(norm[0]))] if norm else []
    # If parsed count mismatches row width, pad/truncate names
    if norm and len(cols) != len(norm[0]):
        width = len(norm[0])
        if len(cols) < width:
            cols = list(cols) + [f"c{i}" for i in range(len(cols), width)]
        else:
            cols = list(cols)[:width]
    return QueryResult(columns=cols, rows=norm, sql=sql, backend="doris", path=path)
