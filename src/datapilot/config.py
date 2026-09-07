"""Runtime configuration from env / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DORIS_URL = "mysql://root@127.0.0.1:9030/ads"


def _default_root() -> Path:
    # package -> src/datapilot -> src -> repo root
    return Path(__file__).resolve().parents[2]


def resolve_query_backend(
    backend: str | None = None,
    *,
    doris_url: str | None = None,
    check_reachable: bool = True,
) -> str:
    """Return ``duckdb`` or ``doris``.

    ``auto``: doris if DATAPILOT_DORIS_URL set and (optionally) reachable, else duckdb.
    """
    raw = (backend or os.getenv("DATAPILOT_QUERY_BACKEND") or "auto").strip().lower()
    url = (doris_url if doris_url is not None else os.getenv("DATAPILOT_DORIS_URL") or "").strip()
    if raw in ("duckdb", "doris"):
        return raw
    # auto
    if not url:
        return "duckdb"
    if not check_reachable:
        return "doris"
    if _doris_reachable(url):
        return "doris"
    return "duckdb"


def _doris_reachable(url: str, timeout: float = 1.5) -> bool:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 9030
        import socket

        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


@dataclass
class Settings:
    llm_mode: str
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    db_path: Path
    guard_mode: str
    trace_dir: Path
    project_root: Path
    guard_url: str | None = None
    guard_catalog: Path | None = None
    guard_policy: Path | None = None
    query_backend: str = "auto"  # duckdb | doris | auto
    doris_url: str | None = None

    @property
    def effective_backend(self) -> str:
        return resolve_query_backend(self.query_backend, doris_url=self.doris_url)

    @property
    def sql_dialect(self) -> str:
        """``duckdb`` or ``mysql`` (Doris FE MySQL protocol)."""
        return "mysql" if self.effective_backend == "doris" else "duckdb"

    @classmethod
    def load(cls) -> "Settings":
        root = _default_root()
        key = os.getenv("OPENAI_API_KEY") or None
        mode = os.getenv("DATAPILOT_LLM_MODE")
        if not mode:
            mode = "openai" if key else "mock"
        db = os.getenv("DATAPILOT_DB_PATH", str(root / "data" / "datapilot.duckdb"))
        trace = os.getenv("DATAPILOT_TRACE_DIR", str(root / "traces"))
        catalog = os.getenv(
            "DATAPILOT_GUARD_CATALOG",
            str(root / "data" / "sqlguard" / "catalog.json"),
        )
        policy = os.getenv(
            "DATAPILOT_GUARD_POLICY",
            str(root / "data" / "sqlguard" / "policy.yaml"),
        )
        guard_url = (os.getenv("DATAPILOT_GUARD_URL") or "").strip() or None
        doris_env = (os.getenv("DATAPILOT_DORIS_URL") or "").strip()
        # Default URL only when backend is doris/auto; empty means auto→duckdb
        doris_url = doris_env or None
        return cls(
            llm_mode=mode.lower(),
            openai_api_key=key,
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            db_path=Path(db),
            guard_mode=os.getenv("DATAPILOT_GUARD_MODE", "auto").lower(),
            trace_dir=Path(trace),
            project_root=root,
            guard_url=guard_url,
            guard_catalog=Path(catalog) if catalog else None,
            guard_policy=Path(policy) if policy else None,
            query_backend=os.getenv("DATAPILOT_QUERY_BACKEND", "auto").lower(),
            doris_url=doris_url,
        )


def get_settings() -> Settings:
    return Settings.load()
