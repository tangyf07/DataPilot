"""Schema/metrics retriever protocol (GameStream interface reserved)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class RetrievedDoc:
    doc_id: str
    title: str
    content: str
    score: float
    source: str = "mock_gamestream"


@runtime_checkable
class SchemaRetriever(Protocol):
    """Reserved for real GameStream ADS docs; mock implements this."""

    def retrieve(self, question: str, intent_name: str | None = None, top_k: int = 3) -> list[RetrievedDoc]:
        ...
