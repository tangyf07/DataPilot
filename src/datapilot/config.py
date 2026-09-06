"""Runtime configuration from env / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _default_root() -> Path:
    # package -> src/datapilot -> src -> repo root
    return Path(__file__).resolve().parents[2]


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
        )


def get_settings() -> Settings:
    return Settings.load()
