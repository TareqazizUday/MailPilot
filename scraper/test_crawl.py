"""
Run website crawl test — output: scraper/output/website_crawl.json

Usage (from project root):
  python -m scraper.test_crawl https://yourdomain.com
  python scraper/test_crawl.py https://yourdomain.com
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(__file__).resolve().parent / "output"
CRAWL_JSON = OUT_DIR / "website_crawl.json"
PROBE_JSON = OUT_DIR / "probe.json"
MIN_INGEST_CHARS = 80

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_app_crawl(start_url: str) -> dict[str, Any]:
    from scraper.crawler import crawl_site
    from scraper.export import (
        build_website_crawl_export,
        documents_from_website_crawl,
        website_crawl_export_to_json,
    )

    pages = crawl_site(start_url=start_url)
    payload = build_website_crawl_export(
        pages,
        start_url=start_url,
        min_section_chars=MIN_INGEST_CHARS,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CRAWL_JSON.write_text(website_crawl_export_to_json(payload), encoding="utf-8")

    docs = documents_from_website_crawl(
        pages,
        start_url=start_url,
        min_section_chars=MIN_INGEST_CHARS,
    )
    stats = (payload.get("crawl") or {}).get("stats") or {}
    pages_list = payload.get("pages") or []

    return {
        "output_file": str(CRAWL_JSON),
        "schema_version": payload.get("schema_version"),
        "pages_fetched": stats.get("pages_fetched", len(pages)),
        "pages_included": stats.get("pages_included", len(pages_list)),
        "pages_skipped_near_duplicate": stats.get("pages_skipped_near_duplicate", 0),
        "paragraphs_deduplicated": stats.get("paragraphs_deduplicated", 0),
        "knowledge_char_count": stats.get("knowledge_char_count", 0),
        "documents_ready_for_ingest": 1 if docs else 0,
        "sample_urls": [p.get("url") for p in pages_list[:8]],
    }


def run_probe(start_url: str, timeout: int) -> dict[str, Any]:
    import requests

    from email_automation.kb.extract import html_to_text

    headers = {
        "User-Agent": "MailPilot-Scraper/1.0",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    err: str | None = None
    status: int | None = None
    html = ""
    try:
        r = requests.get(start_url, headers=headers, timeout=timeout, allow_redirects=True)
        status = r.status_code
        r.raise_for_status()
        html = r.text or ""
    except Exception as e:
        err = str(e)

    if err:
        return {"ok": False, "error": err, "http_status": status}

    text, title = html_to_text(html)
    payload = {
        "schema_version": "1.0",
        "generated_at": _now_iso(),
        "probe": {"url": start_url, "http_status": status, "html_chars": len(html)},
        "page": {"url": start_url, "title": title or start_url, "text": (text or "").strip()},
    }
    _write_json(PROBE_JSON, payload)
    return {"ok": True, "http_status": status, "text_chars": len(text or ""), "saved_json": str(PROBE_JSON)}


def main() -> int:
    ap = argparse.ArgumentParser(description="MailPilot scraper test")
    ap.add_argument("url", nargs="?", default="https://example.com")
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    start_url = (args.url or "").strip()
    if not start_url.startswith(("http://", "https://")):
        print("ERROR: URL must start with http:// or https://")
        return 2

    print(f"\n=== MailPilot scraper ===\nURL: {start_url}\nOutput: {CRAWL_JSON}\n")

    result = run_app_crawl(start_url)
    print(f"Pages in JSON: {result['pages_included']} / fetched {result['pages_fetched']}")
    print(f"Deduped paragraphs: {result['paragraphs_deduplicated']}")
    print(f"Knowledge chars: {result['knowledge_char_count']}")

    report: dict[str, Any] = {"ran_at": _now_iso(), "start_url": start_url, "app_crawl": result}
    if args.probe:
        report["probe"] = run_probe(start_url, args.timeout)

    report["pass"] = result["knowledge_char_count"] > 0
    _write_json(OUT_DIR / "last_run.json", report)
    print(f"\n{'PASS' if report['pass'] else 'FAIL'} — {CRAWL_JSON}\n")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
