from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable
from urllib.parse import urlparse

from email_automation.kb.extract import KBDocument, html_to_text, stable_doc_id

SCHEMA_VERSION = "1.0"
_MIN_DEDUPE_BLOCK_LEN = 48
_PAGE_SIMILARITY_THRESHOLD = 0.92


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _block_hash(text: str) -> str:
    norm = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


def _dedupe_paragraphs(text: str, seen: set[str]) -> tuple[str, int]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", (text or "").strip()) if b.strip()]
    kept: list[str] = []
    skipped = 0
    for block in blocks:
        if len(block) < _MIN_DEDUPE_BLOCK_LEN:
            h = _block_hash(block)
            if h in seen:
                skipped += 1
                continue
            seen.add(h)
            kept.append(block)
            continue
        h = _block_hash(block)
        if h in seen:
            skipped += 1
            continue
        seen.add(h)
        kept.append(block)
    return "\n\n".join(kept), skipped


def _is_near_duplicate_page(text: str, prior_signatures: list[str]) -> bool:
    sample = (text or "")[:4000]
    if not sample:
        return True
    for prev in prior_signatures:
        if SequenceMatcher(None, sample, prev).ratio() >= _PAGE_SIMILARITY_THRESHOLD:
            return True
    return False


def build_website_crawl_export(
    pages: Iterable[Any],
    *,
    start_url: str,
    min_section_chars: int = 80,
) -> dict[str, Any]:
    seen_blocks: set[str] = set()
    page_signatures: list[str] = []
    page_records: list[dict[str, Any]] = []
    knowledge_sections: list[str] = []
    paragraphs_skipped = 0
    pages_fetched = 0
    pages_skipped_short = 0
    pages_skipped_duplicate = 0

    for p in pages:
        pages_fetched += 1
        html = getattr(p, "html", "") or ""
        page_url = getattr(p, "url", "") or ""
        fetched_at = getattr(p, "fetched_at", "") or ""
        text, title = html_to_text(html)
        raw = (text or "").strip()
        if len(raw) < min_section_chars:
            pages_skipped_short += 1
            continue
        deduped, skipped = _dedupe_paragraphs(raw, seen_blocks)
        paragraphs_skipped += skipped
        if len(deduped.strip()) < min_section_chars:
            pages_skipped_short += 1
            continue
        if _is_near_duplicate_page(deduped, page_signatures):
            pages_skipped_duplicate += 1
            continue
        page_signatures.append(deduped[:4000])
        page_title = (title or page_url).strip()
        idx = len(page_records) + 1
        page_records.append(
            {
                "index": idx,
                "url": page_url,
                "title": page_title,
                "fetched_at": fetched_at,
                "char_count": len(deduped),
                "text": deduped,
            }
        )
        knowledge_sections.append(
            f"## {page_title}\nURL: {page_url}\nFetched: {fetched_at}\n\n{deduped}"
        )

    host = urlparse(start_url).netloc or start_url
    knowledge_title = f"Website crawl: {host}"
    knowledge_text = "\n\n---\n\n".join(knowledge_sections)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now_iso(),
        "crawl": {
            "start_url": start_url,
            "site_host": host,
            "stats": {
                "pages_fetched": pages_fetched,
                "pages_included": len(page_records),
                "pages_skipped_too_short": pages_skipped_short,
                "pages_skipped_near_duplicate": pages_skipped_duplicate,
                "paragraphs_deduplicated": paragraphs_skipped,
                "knowledge_char_count": len(knowledge_text),
            },
        },
        "pages": page_records,
        "knowledge": {
            "title": knowledge_title,
            "text": knowledge_text,
        },
    }


def documents_from_website_crawl(
    pages: Iterable[Any],
    *,
    start_url: str,
    min_section_chars: int = 80,
) -> list[KBDocument]:
    payload = build_website_crawl_export(
        pages,
        start_url=start_url,
        min_section_chars=min_section_chars,
    )
    return documents_from_crawl_export(payload)


def documents_from_crawl_export(payload: dict[str, Any]) -> list[KBDocument]:
    knowledge = payload.get("knowledge") or {}
    text = (knowledge.get("text") or "").strip()
    if not text:
        return []
    start_url = ((payload.get("crawl") or {}).get("start_url") or "").strip()
    title = (knowledge.get("title") or f"Website crawl: {start_url}").strip()
    stats = (payload.get("crawl") or {}).get("stats") or {}
    page_urls = [p.get("url") for p in (payload.get("pages") or []) if p.get("url")]
    did = stable_doc_id(source="website", url=start_url, title=title, text=text)
    return [
        KBDocument(
            doc_id=did,
            source="website",
            url=start_url,
            title=title,
            text=text,
            metadata={
                "start_url": start_url,
                "format": "website_crawl_json",
                "schema_version": payload.get("schema_version"),
                "page_count": stats.get("pages_included", len(page_urls)),
                "page_urls": page_urls[:100],
                "paragraphs_deduplicated": stats.get("paragraphs_deduplicated", 0),
            },
        )
    ]


def website_crawl_export_to_json(payload: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=indent)
