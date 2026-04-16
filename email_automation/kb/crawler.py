from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CrawledPage:
    url: str
    html: str
    fetched_at: str


def crawl_site(*, start_url: str, max_pages: int = 40, max_depth: int = 2) -> list[CrawledPage]:
    # Shim: no network crawling.
    _ = (start_url, max_pages, max_depth)
    return []


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

