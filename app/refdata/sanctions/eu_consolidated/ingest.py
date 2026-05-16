"""Ingest the EU Consolidated Financial Sanctions List (FSF), filtered to goods entries.

This list is primarily persons/entities. Goods entries are rare; we capture only those
explicitly tagged or that contain goods keywords. Operator must obtain the URL token from
the EU's Financial Sanctions Database registration page.

USAGE:
    python -m app.refdata.sanctions.eu_consolidated.ingest --file ./data/sanctions/eu_consolidated.xml
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from bs4 import BeautifulSoup

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import upsert_sanctioned_commodities
from app.telemetry import configure_logging, log

PROVENANCE = "https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/"

GOODS_KEYWORDS = (
    "goods",
    "equipment",
    "material",
    "weapon",
    "missile",
    "uranium",
    "centrifuge",
    "tank",
    "munition",
    "explosive",
    "vessel",
)


def _parse(xml_path: Path) -> list[dict]:
    soup = BeautifulSoup(xml_path.read_text(encoding="utf-8", errors="replace"), "lxml-xml")
    items: list[dict] = []
    for entity in soup.find_all(["entity", "ENTITY"]):
        text = entity.get_text(" ", strip=True)
        lower = text.lower()
        if not any(k in lower for k in GOODS_KEYWORDS):
            continue
        ref = entity.get("logicalId") or entity.get("euReferenceNumber") or text[:32]
        items.append(
            {
                "source_record_id": str(ref),
                "description": text[:2000],
                "hs_codes": [],
                "restriction_type": "prohibited",
                "provenance_url": PROVENANCE,
            }
        )
    return items


async def main_async(file: Path) -> None:
    configure_logging()
    if not file.exists():
        log.error("eu_consolidated.file_missing", path=str(file))
        return
    items = _parse(file)
    log.info("eu_consolidated.parsed", n=len(items))
    async with with_run_logging("EU_CONSOLIDATED", notes=f"file={file}") as (db, run):
        counts = await upsert_sanctioned_commodities(db, items, source="EU_CONSOLIDATED", run=run)
        run.rows_upserted = counts["sanctioned"]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main_async(args.file))


if __name__ == "__main__":
    main()
