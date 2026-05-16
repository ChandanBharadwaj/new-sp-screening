"""Parse cached CROSS ruling HTML into hs_training_example rows.

Each ruling page on rulings.cbp.gov carries (a) a description of the goods in
question and (b) a definitive HTSUS classification CBP assigned. We extract both
and drop rulings that lack either.

USAGE:
    python -m app.refdata.cross.ingest --html-dir data/cross_raw/rulings
"""
from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from bs4 import BeautifulSoup
from sqlalchemy.dialects.postgresql import insert

from app.db.models import HsTrainingExample
from app.refdata.common import batches, lazy_embedder, update_tsv_for_table, with_run_logging
from app.telemetry import log

DEFAULT_HTML_DIR = Path("data/cross_raw/rulings")

# CBP rulings cite HTSUS codes formatted as 1234.56.7890 or 1234.56 (8-10 digits truncated).
HS_CODE_RE = re.compile(r"\b(\d{4}\.\d{2}(?:\.\d{2,4})?)\b")
RULING_ID_RE = re.compile(r"\b([A-Z]{1,3}\d{5,9})\b")


def _normalize_code(raw: str) -> str | None:
    digits = re.sub(r"[^0-9]", "", raw or "")
    if len(digits) < 6:
        return None
    return digits[:6]


def _extract_text_block(soup: BeautifulSoup, header_keywords: tuple[str, ...]) -> str | None:
    """Find a header element whose text contains one of `header_keywords`, return the next sibling block's text."""
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b"]):
        text = (tag.get_text(" ", strip=True) or "").lower()
        if any(kw.lower() in text for kw in header_keywords):
            cur = tag.find_next_sibling()
            captured: list[str] = []
            while cur and cur.name not in ("h1", "h2", "h3", "h4"):
                t = cur.get_text(" ", strip=True)
                if t:
                    captured.append(t)
                cur = cur.find_next_sibling()
            block = " ".join(captured).strip()
            if block:
                return block
    return None


def _parse_ruling(html: str, filename_stem: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(" ", strip=True)

    # Ruling ID — try meta/title first, then body
    ruling_id: str | None = None
    title = soup.find("title")
    if title:
        m = RULING_ID_RE.search(title.get_text(" ", strip=True))
        if m:
            ruling_id = m.group(1)
    if not ruling_id:
        m = RULING_ID_RE.search(body_text[:500])
        if m:
            ruling_id = m.group(1)
    if not ruling_id:
        ruling_id = filename_stem

    # Description — prefer a labeled "merchandise"/"goods"/"product" section, else first
    # 200 chars of body after stripping boilerplate.
    description = _extract_text_block(soup, ("merchandise", "product", "goods", "description of"))
    if not description:
        # Drop disclaimer/header boilerplate by selecting the longest <p> in the document.
        ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        ps = [p for p in ps if len(p) > 80]
        description = max(ps, key=len) if ps else None
    if not description:
        return None
    description = description[:2000]

    # HS code — search for explicit "classified under" / "classification" wording,
    # then fall back to any HTS-format code in the document.
    hs_section = _extract_text_block(soup, ("classification", "classified under", "classifiable"))
    candidate_codes: list[str] = []
    for section in (hs_section or "", body_text):
        for m in HS_CODE_RE.finditer(section):
            c = _normalize_code(m.group(1))
            if c:
                candidate_codes.append(c)
    if not candidate_codes:
        return None

    # Take the most frequent code; tie-break: first occurrence.
    from collections import Counter

    code_counts = Counter(candidate_codes)
    hs_code = code_counts.most_common(1)[0][0]

    return {"ruling_id": ruling_id, "description": description, "hs_code": hs_code}


def _parse_dir(directory: Path) -> list[dict]:
    items: list[dict] = []
    if not directory.exists():
        log.warning("cross.html_dir_missing", path=str(directory))
        return items
    files = list(directory.glob("*.html"))
    log.info("cross.parsing_dir", path=str(directory), n_files=len(files))
    for f in files:
        try:
            rec = _parse_ruling(f.read_text(encoding="utf-8", errors="replace"), f.stem)
            if rec:
                items.append(rec)
        except Exception as e:
            log.warning("cross.html_parse_failed", file=str(f), error=str(e))
    return items


async def _upsert(items: list[dict]) -> int:
    if not items:
        return 0
    embedder = lazy_embedder()
    async with with_run_logging("CROSS", notes=f"n_records={len(items)}") as (db, run):
        n = 0
        for batch in batches(items, 64):
            descs = [it["description"] for it in batch]
            vectors = embedder.encode_batch(descs)
            for it, v in zip(batch, vectors, strict=True):
                stmt = insert(HsTrainingExample).values(
                    source="cross_ruling",
                    source_id=it.get("ruling_id"),
                    description=it["description"],
                    hs_code=it["hs_code"],
                    embedding=v.tolist(),
                )
                stmt = stmt.on_conflict_do_nothing()
                await db.execute(stmt)
                n += 1
            await db.commit()
            log.info("cross.upsert_progress", rows=n)
        await update_tsv_for_table(db, "hs_training_example", columns=("description",))
        await db.commit()
        run.rows_upserted = n
        return n


async def main_async(html_dir: Path) -> None:
    items = _parse_dir(html_dir)
    log.info("cross.parsed", n=len(items))
    await _upsert(items)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--html-dir", type=Path, default=DEFAULT_HTML_DIR)
    args = p.parse_args()
    asyncio.run(main_async(args.html_dir))


if __name__ == "__main__":
    main()
