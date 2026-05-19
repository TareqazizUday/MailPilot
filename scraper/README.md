# MailPilot Scraper

Website scraper: multi-page crawl, deduplicated JSON export, KB ingest.

## Layout

| File | Role |
|------|------|
| `crawler.py` | BFS crawl (same domain, robots.txt) |
| `export.py` | Dedupe + `website_crawl` JSON schema |
| `bundle.py` | `mailpilot_kb_bundle` for Setup editor |
| `test_crawl.py` | CLI test |
| `output/` | Test output (`website_crawl.json`) |

## Setup integration

- **Start Crawl & Ingest** → `POST /api/kb/crawl` → pgvector (per `user.id` tenant)
- Saves `data/users/<id>/website_crawl.json`
- Poll `GET /api/kb/crawl/status`
- **Edit KB JSON** → `GET /api/kb/export-bundle` (crawl + documents)

## Test

```bash
python -m scraper.test_crawl https://yourdomain.com
```
