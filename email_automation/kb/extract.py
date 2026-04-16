from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class KBDocument:
    doc_id: str
    source: str
    url: str
    title: str
    text: str
    metadata: dict[str, Any]


def stable_doc_id(*, source: str, url: str, title: str, text: str) -> str:
    h = hashlib.sha256()
    h.update((source or "").encode("utf-8"))
    h.update(b"\n")
    h.update((url or "").encode("utf-8"))
    h.update(b"\n")
    h.update((title or "").encode("utf-8"))
    h.update(b"\n")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()[:24]


def chunk_text(text: str, *, max_chars: int = 1200, overlap: int = 120) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    max_chars = max(200, int(max_chars))
    overlap = max(0, min(int(overlap), max_chars // 3))
    chunks: list[str] = []
    i = 0
    while i < len(t):
        j = min(len(t), i + max_chars)
        chunks.append(t[i:j])
        if j >= len(t):
            break
        i = max(0, j - overlap)
    return chunks


def html_to_text(html: str) -> Tuple[str, str]:
    raw = html or ""
    soup = BeautifulSoup(raw, "html.parser")
    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    for tag in soup(["script", "style", "noscript"]):
        try:
            tag.decompose()
        except Exception:
            pass
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, title


def documents_from_json_upload(data: Any, *, source_name: str) -> list[KBDocument]:
    # Accept either a list of {title,url,text} or a dict with "documents"
    docs: Iterable[Any]
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        docs = data["documents"]
    elif isinstance(data, list):
        docs = data
    else:
        docs = []

    out: list[KBDocument] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        url = str(d.get("url") or "").strip()
        title = str(d.get("title") or "").strip()
        text = str(d.get("text") or "").strip()
        if not text:
            continue
        did = stable_doc_id(source=source_name, url=url, title=title, text=text)
        out.append(
            KBDocument(
                doc_id=did,
                source=source_name,
                url=url,
                title=title or url,
                text=text,
                metadata={"source_name": source_name},
            )
        )
    return out


def documents_to_json(docs: list[KBDocument]) -> str:
    return json.dumps([d.__dict__ for d in docs], ensure_ascii=False, indent=2)

