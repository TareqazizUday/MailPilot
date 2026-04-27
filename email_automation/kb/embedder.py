from __future__ import annotations

import logging
import os

from email_automation.settings import Settings

log = logging.getLogger("mailpilot.kb.embedder")
_warned_no_key = False
_EMBED_BATCH = 64


def _api_key(settings: Settings) -> str:
    k = settings.LLM_API_KEY
    if k is not None:
        s = (k.get_secret_value() or "").strip()
        if s:
            return s
    for name in ("OPENAI_API_KEY", "LLM_API_KEY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return ""


def _normalize_vec(vec: list[float], dim: int) -> list[float]:
    if len(vec) == dim:
        return vec
    if len(vec) > dim:
        return list(vec[:dim])
    return vec + [0.0] * (dim - len(vec))


def _embed_openai(
    *, settings: Settings, texts: list[str], key: str, model: str, dim: int
) -> list[list[float]]:
    from openai import OpenAI

    client = OpenAI(api_key=key)
    out: list[list[float]] = []
    tlist = [t or " " for t in texts]
    for i in range(0, len(tlist), _EMBED_BATCH):
        batch = tlist[i : i + _EMBED_BATCH]
        resp = client.embeddings.create(model=model, input=batch)
        for item in resp.data:
            v = [float(x) for x in item.embedding]
            out.append(_normalize_vec(v, dim))
    return out


def embed_texts(*, settings: Settings, texts: list[str]) -> list[list[float]]:
    ed = (os.environ.get("EMBEDDING_DIM") or "").strip()
    if ed.isdigit():
        dim = int(ed)
    else:
        dim = int(getattr(settings, "EMBEDDING_DIM", 1536) or 1536)
    raw: list[str] = list(texts or [])
    if not raw:
        return []

    model = (
        os.environ.get("EMBEDDING_MODEL")
        or getattr(settings, "EMBEDDING_MODEL", None)
        or "text-embedding-3-small"
    )
    model = (model or "").strip()
    if model.lower() in ("", "stub", "none", "off"):
        return [[0.0] * dim for _ in raw]

    key = _api_key(settings)
    if not key:
        global _warned_no_key
        if not _warned_no_key:
            _warned_no_key = True
            log.info(
                "No LLM/OPENAI key; using zero vectors for KB (set LLM_API_KEY or OPENAI_API_KEY for real embeddings)."
            )
        return [[0.0] * dim for _ in raw]

    try:
        return _embed_openai(settings=settings, texts=raw, key=key, model=model, dim=dim)
    except Exception as e:
        log.warning("OpenAI embed failed, zero vectors: %s", e)
        return [[0.0] * dim for _ in raw]
