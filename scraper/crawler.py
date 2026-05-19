from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Optional
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_USER_AGENT = "MailPilot-Scraper/1.0 (+https://github.com/local/dev)"
_REQUEST_TIMEOUT = 20
_DELAY_SEC = 0.3
DEFAULT_MAX_PAGES = 80
DEFAULT_MAX_DEPTH = 3

_SKIP_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".zip",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".css",
    ".js",
    ".xml",
    ".json",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)


@dataclass(frozen=True)
class CrawledPage:
    url: str
    html: str
    fetched_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host_key(netloc: str) -> str:
    h = (netloc or "").lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return h


def _same_site(start_netloc: str, url: str) -> bool:
    try:
        return _host_key(urlparse(url).netloc) == _host_key(start_netloc)
    except Exception:
        return False


def _normalize_url(url: str, base: str) -> Optional[str]:
    raw = (url or "").strip()
    if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None
    try:
        abs_url = urljoin(base, raw)
        p = urlparse(abs_url)
        if p.scheme not in ("http", "https"):
            return None
        path = p.path or "/"
        path_lower = path.lower()
        for ext in _SKIP_EXTENSIONS:
            if path_lower.endswith(ext):
                return None
        norm = urlunparse(
            (
                p.scheme.lower(),
                p.netloc.lower(),
                path.rstrip("/") if path != "/" else "/",
                "",
                p.query,
                "",
            )
        )
        return norm
    except Exception:
        return None


def _load_robots(start_url: str) -> Optional[RobotFileParser]:
    try:
        p = urlparse(start_url)
        robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp
    except Exception:
        return None


def _allowed(robots: Optional[RobotFileParser], url: str) -> bool:
    if robots is None:
        return True
    try:
        return robots.can_fetch(_USER_AGENT, url)
    except Exception:
        return True


def _extract_links(html: str, base_url: str) -> list[str]:
    out: list[str] = []
    try:
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.find_all("a", href=True):
            norm = _normalize_url(a.get("href", ""), base_url)
            if norm:
                out.append(norm)
    except Exception:
        pass
    return out


def _fetch_page(url: str, session: requests.Session) -> Optional[str]:
    try:
        r = session.get(url, timeout=_REQUEST_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            logger.warning("crawl skip %s status=%s", url, r.status_code)
            return None
        ctype = (r.headers.get("Content-Type") or "").lower()
        if ctype and "html" not in ctype and "text/" not in ctype:
            return None
        text = r.text or ""
        if not text.strip():
            return None
        return text
    except Exception as e:
        logger.warning("crawl fetch failed %s: %s", url, e)
        return None


def _emit_progress(
    on_progress: Callable[[dict[str, Any]], None] | None,
    *,
    phase: str,
    pages_fetched: int,
    max_pages: int,
    current_url: str = "",
) -> None:
    if not on_progress:
        return
    cap = max(1, max_pages)
    # Scraping phase maps to ~5–70% of overall job (export + ingest follow in views).
    percent = min(70, int(5 + (pages_fetched / cap) * 65))
    try:
        on_progress(
            {
                "phase": phase,
                "percent": percent,
                "pages_fetched": pages_fetched,
                "max_pages": max_pages,
                "current_url": current_url,
                "message": f"Fetching pages ({pages_fetched}/{max_pages})…",
            }
        )
    except Exception:
        pass


def crawl_site(
    *,
    start_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[CrawledPage]:
    """BFS crawl of HTML pages on the same host as start_url."""
    start = _normalize_url(start_url, start_url)
    if not start:
        return []

    max_pages = max(1, min(int(max_pages or DEFAULT_MAX_PAGES), 200))
    max_depth = max(0, min(int(max_depth or DEFAULT_MAX_DEPTH), 5))
    _emit_progress(on_progress, phase="crawling", pages_fetched=0, max_pages=max_pages, current_url=start)

    start_netloc = urlparse(start).netloc
    robots = _load_robots(start)
    visited: set[str] = set()
    queue: Deque[tuple[str, int]] = deque([(start, 0)])
    pages: list[CrawledPage] = []

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if not _allowed(robots, url):
            continue

        html = _fetch_page(url, session)
        time.sleep(_DELAY_SEC)

        if html is None:
            continue

        pages.append(CrawledPage(url=url, html=html, fetched_at=_now_iso()))
        _emit_progress(
            on_progress,
            phase="crawling",
            pages_fetched=len(pages),
            max_pages=max_pages,
            current_url=url,
        )

        if depth >= max_depth:
            continue

        for link in _extract_links(html, url):
            if link in visited:
                continue
            if not _same_site(start_netloc, link):
                continue
            if not _allowed(robots, link):
                continue
            queue.append((link, depth + 1))

    return pages
