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
    cols = list(columns) if columns else (
        [f"c{i}" for i in range(len(norm[0]))] if norm else []
    )
    return QueryResult(columns=cols, rows=norm, sql=sql, backend="doris", path=path)
