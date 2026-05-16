"""Polite paginated scraper for US CBP CROSS rulings (rulings.cbp.gov).

USAGE:
    python -m app.refdata.cross.scraper --pages 5 --query "*"

CROSS rate-limits aggressively; we sleep 1s between requests and cache HTML to
./data/cross_raw/. The scraper does NOT load anything into Postgres — that's
ingest.py's job.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

import httpx

from app.telemetry import configure_logging, log

BASE = "https://rulings.cbp.gov"
SEARCH_URL = BASE + "/search"
CACHE_DIR = Path("data/cross_raw")


def _cache_path(url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return CACHE_DIR / f"{h}.html"


async def fetch(client: httpx.AsyncClient, url: str) -> str | None:
    cached = _cache_path(url)
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
        if r.status_code != 200:
            log.warning("cross.fetch_non_200", url=url, status=r.status_code)
            return None
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(r.text, encoding="utf-8")
        return r.text
    except Exception as e:
        log.warning("cross.fetch_error", url=url, error=str(e))
        return None


async def main_async(pages: int, query: str) -> None:
    configure_logging()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "commodity-screening-poc/0.1 (research)"}
    async with httpx.AsyncClient(headers=headers) as client:
        for page in range(1, pages + 1):
            url = f"{SEARCH_URL}?term={query}&page={page}"
            log.info("cross.fetch_page", page=page, url=url)
            html = await fetch(client, url)
            if not html:
                continue
            await asyncio.sleep(1.0)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=1)
    p.add_argument("--query", type=str, default="*")
    args = p.parse_args()
    asyncio.run(main_async(args.pages, args.query))


if __name__ == "__main__":
    main()
