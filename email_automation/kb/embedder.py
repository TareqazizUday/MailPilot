from __future__ import annotations

from email_automation.settings import Settings


def embed_texts(*, settings: Settings, texts: list[str]) -> list[list[float]]:
    # Shim: deterministic zero vectors.
    dim = int(getattr(settings, "EMBEDDING_DIM", 1536) or 1536)
    return [[0.0] * dim for _ in (texts or [])]

