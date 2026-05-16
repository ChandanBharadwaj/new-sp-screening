"""Polite paginated scraper for US CBP CROSS rulings (rulings.cbp.gov).

Two-pass crawl:
1. Walk search-results pages, extract per-ruling detail URLs.
2. Fetch each ruling detail page, cache under data/cross_raw/rulings/{ruling_id}.html.

USAGE:
    python -m app.refdata.cross.scraper --max-rulings 5000
    python -m app.refdata.cross.scraper --max-rulings 5000 --query "*"
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from app.telemetry import configure_logging, log

BASE = "https://rulings.cbp.gov"
SEARCH_URL = BASE + "/search"
SEARCH_CACHE = Path("data/cross_raw/search")
RULING_CACHE = Path("data/cross_raw/rulings")

RULING_ID_RE = re.compile(r"/ruling/([A-Z0-9_\-]+)", re.IGNORECASE)


def _cache_path(directory: Path, url: str) -> Path:
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return directory / f"{h}.html"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
async def _http_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(url, timeout=30, follow_redirects=True)
    if r.status_code >= 500:
        raise RuntimeError(f"server error {r.status_code} on {url}")
    return r


async def _fetch_cached(client: httpx.AsyncClient, url: str, cache_dir: Path) -> str | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(cache_dir, url)
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")
    try:
        r = await _http_get(client, url)
        if r.status_code != 200:
            log.warning("cross.fetch_non_200", url=url, status=r.status_code)
            return None
        cached.write_text(r.text, encoding="utf-8")
        return r.text
    except Exception as e:
        log.warning("cross.fetch_error", url=url, error=str(e))
        return None


def _extract_ruling_urls(search_html: str) -> list[str]:
    soup = BeautifulSoup(search_html, "lxml")
    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = RULING_ID_RE.search(href)
        if not m:
            continue
        full = urljoin(BASE, href)
        # canonicalize: strip query / fragment
        parsed = urlparse(full)
        canon = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if canon in seen:
            continue
        seen.add(canon)
        urls.append(canon)
    return urls


async def main_async(max_rulings: int, query: str, rps: float) -> None:
    configure_logging()
    SEARCH_CACHE.mkdir(parents=True, exist_ok=True)
    RULING_CACHE.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "commodity-screening-poc/0.1 (open-source research)",
        "Accept": "text/html",
    }
    sleep_s = max(0.0, 1.0 / max(rps, 0.1))

    collected: list[str] = []
    seen: set[str] = set()

    async with httpx.AsyncClient(headers=headers) as client:
        page = 1
        while len(collected) < max_rulings:
            url = f"{SEARCH_URL}?term={query}&page={page}"
            log.info("cross.fetch_search_page", page=page, collected=len(collected))
            html = await _fetch_cached(client, url, SEARCH_CACHE)
            await asyncio.sleep(sleep_s)
            if not html:
                break
            new_urls = [u for u in _extract_ruling_urls(html) if u not in seen]
            if not new_urls:
                log.info("cross.no_new_links_on_page", page=page)
                break
            for u in new_urls:
                seen.add(u)
                collected.append(u)
                if len(collected) >= max_rulings:
                    break
            page += 1

        log.info("cross.discovered_rulings", n=len(collected))

        n_fetched = 0
        for u in collected[:max_rulings]:
            html = await _fetch_cached(client, u, RULING_CACHE)
            await asyncio.sleep(sleep_s)
            if html:
                n_fetched += 1
            if n_fetched % 100 == 0 and n_fetched > 0:
                log.info("cross.ruling_progress", fetched=n_fetched, total=len(collected))

    log.info("cross.done", discovered=len(collected), fetched=n_fetched)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--max-rulings", type=int, default=5000)
    p.add_argument("--query", type=str, default="*")
    p.add_argument("--rps", type=float, default=1.0, help="requests per second")
    args = p.parse_args()
    asyncio.run(main_async(args.max_rulings, args.query, args.rps))


if __name__ == "__main__":
    main()
