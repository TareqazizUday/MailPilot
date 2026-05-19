from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from email_automation.kb.extract import KBDocument, documents_from_json_upload

from scraper.export import documents_from_crawl_export

BUNDLE_EXPORT_TYPE = "mailpilot_kb_bundle"
BUNDLE_SCHEMA_VERSION = "1.0"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_website_crawl_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def build_kb_export_bundle(
    *,
    vector_documents: list[dict[str, Any]],
    website_crawl: dict[str, Any] | None,
) -> dict[str, Any]:
    simple_docs: list[dict[str, Any]] = []
    for d in vector_documents or []:
        simple_docs.append(
            {
                "title": d.get("title") or "",
                "url": d.get("url") or "",
                "text": d.get("text") or "",
                "source": d.get("source") or "",
                "doc_id": d.get("doc_id") or "",
            }
        )
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "export_type": BUNDLE_EXPORT_TYPE,
        "generated_at": _utc_now_iso(),
        "website_crawl": website_crawl,
        "documents": simple_docs,
    }


def is_kb_bundle(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("export_type") == BUNDLE_EXPORT_TYPE


def documents_from_kb_bundle(payload: dict[str, Any]) -> list[KBDocument]:
    """Build KB documents from mailpilot_kb_bundle or legacy {documents} JSON."""
    out: list[KBDocument] = []
    seen: set[str] = set()

    wc = payload.get("website_crawl")
    if isinstance(wc, dict) and (wc.get("knowledge") or {}).get("text"):
        for doc in documents_from_crawl_export(wc):
            seen.add(doc.doc_id)
            out.append(doc)

    raw_docs = payload.get("documents")
    if isinstance(raw_docs, list) and raw_docs:
        uploaded = documents_from_json_upload({"documents": raw_docs}, source_name="kb_bundle.json")
        for doc in uploaded:
            if doc.doc_id in seen:
                continue
            seen.add(doc.doc_id)
            out.append(doc)

    if not out and not is_kb_bundle(payload):
        for doc in documents_from_json_upload(payload, source_name="kb_edit.json"):
            if doc.doc_id not in seen:
                seen.add(doc.doc_id)
                out.append(doc)

    return out


def save_website_crawl_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_website_crawl_file(path: Path) -> bool:
    """Remove per-user website crawl JSON from disk. Returns True if a file was deleted."""
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        pass
    return False
