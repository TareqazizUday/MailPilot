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
    # Accept either:
    # - a list of {title,url,text}
    # - a dict with "documents": [...]
    # - any other dict JSON: treated as a single document by flattening to text
    def _get_nested_str(obj: Any, path: list[str]) -> str:
        cur = obj
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                return ""
            cur = cur.get(k)
        return str(cur or "").strip()

    def _format_scalar(v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str):
            return v.strip()
        return str(v).strip()

    def _flatten_json_to_lines(obj: Any) -> list[str]:
        # Produce readable "path: value" lines (good for chunking/embeddings).
        max_value_chars = 800
        max_total_chars = 120_000
        max_lines = 4_000

        lines: list[str] = []
        total = 0

        def add_line(s: str) -> None:
            nonlocal total
            if not s:
                return
            if len(lines) >= max_lines or total >= max_total_chars:
                return
            s2 = s.strip()
            if not s2:
                return
            if len(s2) > max_value_chars:
                s2 = s2[: max_value_chars - 3] + "..."
            lines.append(s2)
            total += len(s2) + 1

        def walk(x: Any, prefix: str) -> None:
            if len(lines) >= max_lines or total >= max_total_chars:
                return

            if isinstance(x, dict):
                for k, v in x.items():
                    key = str(k)
                    p2 = f"{prefix}.{key}" if prefix else key
                    walk(v, p2)
                return

            if isinstance(x, list):
                # If list is scalar-like, compress into one line.
                scalars: list[str] = []
                all_scalar = True
                for it in x:
                    if isinstance(it, (dict, list)):
                        all_scalar = False
                        break
                    s = _format_scalar(it)
                    if s:
                        scalars.append(s)
                if all_scalar:
                    if scalars:
                        add_line(f"{prefix}: " + ", ".join(scalars))
                    return
                # Otherwise walk each element with an index.
                for i, it in enumerate(x):
                    walk(it, f"{prefix}[{i}]")
                return

            val = _format_scalar(x)
            if not val:
                return
            add_line(f"{prefix}: {val}" if prefix else val)

        walk(obj, "")
        return lines

    docs: Iterable[Any]
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        docs = data["documents"]
    elif isinstance(data, list):
        docs = data
    elif isinstance(data, dict):
        # Fallback: treat arbitrary dict JSON as one document.
        website = _get_nested_str(data, ["source", "website"])
        title = _get_nested_str(data, ["source", "title"]) or _get_nested_str(data, ["brand", "name"]) or source_name
        lines = _flatten_json_to_lines(data)
        text = "\n".join(lines).strip()
        if not text:
            return []
        did = stable_doc_id(source=source_name, url=website, title=title, text=text)
        return [
            KBDocument(
                doc_id=did,
                source=source_name,
                url=website,
                title=title or website or source_name,
                text=text,
                metadata={"source_name": source_name, "website": website, "title": title},
            )
        ]
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

