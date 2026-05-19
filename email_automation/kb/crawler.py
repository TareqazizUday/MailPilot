"""Backward-compatible shim — implementation in scraper.crawler."""

from scraper.crawler import CrawledPage, crawl_site

__all__ = ["CrawledPage", "crawl_site"]
