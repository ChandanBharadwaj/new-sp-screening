"""Ingest the UN Consolidated Sanctions List XML, filtered to goods entries.

The UN list is primarily entities/persons. We capture only entries explicitly marked
as goods/materials (e.g., DPRK luxury items, Iran proliferation items). No fabrication;
items without sufficient detail are dropped.

USAGE:
    python -m app.refdata.sanctions.un.ingest --file ./data/sanctions/un_consolidated.xml
    python -m app.refdata.sanctions.un.ingest --download
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import insert_aliases, upsert_sanctioned_commodities
from app.telemetry import configure_logging, log

UN_XML_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
DEFAULT_CACHE = Path("data/sanctions/un_consolidated.xml")
PROVENANCE = "https://main.un.org/securitycouncil/en/sanctions/un-sc-consolidated-list"

GOODS_KEYWORDS = (
    "luxury",
    "weapon",
    "missile",
    "uranium",
    "centrifuge",
    "tank",
    "munition",
    "explosive",
    "chemical precursor",
)


async def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        return dest
    async with httpx.AsyncClient(timeout=120) as client:
        log.info("un.downloading", url=url)
        r = await client.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def _extract_aliases(ent) -> list[dict]:
    """UN XML nests aliases under `<INDIVIDUAL_ALIAS>` / `<ENTITY_ALIAS>`."""
    out: list[dict] = []
    for tag in ent.find_all(["INDIVIDUAL_ALIAS", "ENTITY_ALIAS", "individual_alias", "entity_alias"]):
        name_el = tag.find(["ALIAS_NAME", "alias_name"])
        name = name_el.get_text(strip=True) if name_el else None
        if name:
            out.append({"alias": name, "alias_kind": "aka"})
    return out


def _parse(xml_path: Path) -> list[dict]:
    soup = BeautifulSoup(xml_path.read_text(encoding="utf-8", errors="replace"), "lxml-xml")
    items: list[dict] = []
    for ent in soup.find_all(["INDIVIDUAL", "ENTITY"]):
        text_parts = []
        for tag in ent.find_all(string=True):
            t = str(tag).strip()
            if t:
                text_parts.append(t)
        text = " ".join(text_parts)
        lower = text.lower()
        if not any(kw in lower for kw in GOODS_KEYWORDS):
            continue
        ref = ent.find("REFERENCE_NUMBER") or ent.find("DATAID")
        ref_id = (ref.get_text(strip=True) if ref else None) or text[:32]
        items.append(
            {
                "source_record_id": ref_id,
                "description": text[:2000],
                "hs_codes": [],
                "restriction_type": "prohibited",
                "provenance_url": PROVENANCE,
                "_aliases": _extract_aliases(ent),
            }
        )
    return items


async def main_async(file: Path | None, download: bool) -> None:
    configure_logging()
    if download or file is None:
        file = await _download(UN_XML_URL, DEFAULT_CACHE)
    items = _parse(file)
    log.info(
        "un.parsed",
        n=len(items),
        with_aliases=sum(1 for r in items if r.get("_aliases")),
    )

    async with with_run_logging("UN_CONSOLIDATED", notes=f"file={file}") as (db, run):
        upsert_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in items]
        counts = await upsert_sanctioned_commodities(
            db, upsert_rows, source="UN_CONSOLIDATED", run=run
        )
        run.rows_upserted = counts["sanctioned"]
        n_aliases = 0
        for r in items:
            n_aliases += await insert_aliases(
                db,
                source="UN_CONSOLIDATED",
                source_record_id=r["source_record_id"],
                aliases=r.get("_aliases") or [],
            )
        await db.commit()
        run.notes = (run.notes or "") + f" | aliases={n_aliases}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, default=None)
    p.add_argument("--download", action="store_true")
    args = p.parse_args()
    asyncio.run(main_async(args.file, args.download))


if __name__ == "__main__":
    main()
