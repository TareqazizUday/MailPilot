from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from email_automation.settings import Settings


@dataclass
class _Stats:
    documents: int = 0
    chunks: int = 0


class VectorStore:
    """Minimal vector store shim (no external DB required)."""

    def __init__(self, *, settings: Settings, tenant_id: str):
        self.settings = settings
        self.tenant_id = tenant_id
        self._stats = _Stats()

    def upsert_document_with_chunks(
        self,
        *,
        doc_id: str,
        source: str,
        url: str,
        title: str,
        metadata: dict[str, Any],
        chunks: Iterable[Tuple[str, list[float]]],
    ) -> None:
        _ = (doc_id, source, url, title, metadata)
        cnt = len(list(chunks))
        self._stats.documents += 1
        self._stats.chunks += cnt

    def stats(self) -> dict[str, Any]:
        return {"documents": int(self._stats.documents), "chunks": int(self._stats.chunks)}

