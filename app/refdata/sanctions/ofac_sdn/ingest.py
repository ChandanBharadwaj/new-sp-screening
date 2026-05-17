"""Ingest the US Treasury OFAC SDN list (sdn.csv + add.csv + alt.csv).

OFAC SDN identifies persons, entities, and vessels designated by the US Treasury for
sanctions enforcement. Although this engine is commodity-focused (party screening is
v2 per README C2), SDN entries with country-program tags (IRAN, DPRK, SYRIA, CUBA,
VENEZUELA) attach derived country_rule rows so that shipments routed to those
destinations match against SDN descriptions via the existing structured + semantic paths.
Aliases are persisted to `sanctioned_commodity_alias` for the trigram-fuzzy path
added in the sanctions normalization fix.

INPUT:
  --sdn  : path to sdn.csv
  --add  : path to add.csv  (optional)
  --alt  : path to alt.csv  (optional)

USAGE:
    python -m app.refdata.sanctions.ofac_sdn.ingest \\
        --sdn ./data/sanctions/ofac/sdn.csv \\
        --add ./data/sanctions/ofac/add.csv \\
        --alt ./data/sanctions/ofac/alt.csv
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models import SanctionedCommodity, SanctionedCommodityAlias
from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import upsert_sanctioned_commodities
from app.refdata.sanctions.ofac_sdn.parser import SdnRecord, parse
from app.telemetry import configure_logging, log

PROVENANCE = "https://sanctionslist.ofac.treas.gov/Home/SdnList"


def _record_to_row(rec: SdnRecord) -> dict:
    """Project an SdnRecord into the dict shape expected by upsert_sanctioned_commodities."""
    description_parts = [rec.name]
    if rec.sdn_type:
        description_parts.append(f"({rec.sdn_type})")
    if rec.programs:
        description_parts.append("| programs: " + ", ".join(rec.programs))
    if rec.title:
        description_parts.append(f"| title: {rec.title}")
    if rec.countries:
        description_parts.append("| countries: " + ", ".join(rec.countries))
    description = " ".join(description_parts)[:2000]

    # Country rules: blanket destination-block for comprehensive-embargo programs.
    country_rules = [
        {"origin_iso": None, "destination_iso": iso, "restriction_type": "blocked"}
        for iso in rec.derived_destination_isos
    ]

    return {
        "source_record_id": rec.ent_num,
        "description": description,
        "hs_codes": [],  # SDN is party-based; HS codes not applicable
        "restriction_type": "blocked",
        "provenance_url": PROVENANCE,
        "country_rules": country_rules,
        # Carried through to the alias upsert below — not consumed by the shared upserter.
        "_aliases": rec.aliases,
    }


async def main_async(sdn_file: Path, add_file: Path | None, alt_file: Path | None) -> None:
    configure_logging()
    log.info("ofac_sdn.parsing", sdn=str(sdn_file), add=str(add_file), alt=str(alt_file))
    records = parse(sdn_file, add_file, alt_file)
    log.info(
        "ofac_sdn.parsed",
        n=len(records),
        with_aliases=sum(1 for r in records if r.aliases),
        with_addresses=sum(1 for r in records if r.addresses),
    )

    items = [_record_to_row(r) for r in records]

    async with with_run_logging(
        "OFAC_SDN", notes=f"sdn={sdn_file} add={add_file} alt={alt_file}"
    ) as (db, run):
        counts = await upsert_sanctioned_commodities(
            db,
            [{k: v for k, v in r.items() if not k.startswith("_")} for r in items],
            source="OFAC_SDN",
            run=run,
        )
        run.rows_upserted = counts["sanctioned"]

        # Second pass: insert aliases. The shared upserter already keyed each record
        # by (source, source_record_id); look those IDs back up.
        n_aliases = 0
        for r in items:
            aliases = r.get("_aliases") or []
            if not aliases:
                continue
            sid = (
                await db.execute(
                    select(SanctionedCommodity.id).where(
                        SanctionedCommodity.source == "OFAC_SDN",
                        SanctionedCommodity.source_record_id == r["source_record_id"],
                    )
                )
            ).scalar_one_or_none()
            if sid is None:
                continue
            for a in aliases:
                stmt = pg_insert(SanctionedCommodityAlias).values(
                    sanctioned_commodity_id=sid,
                    alias=a["alias"][:500],
                    alias_kind=a.get("alias_kind"),
                )
                await db.execute(stmt)
                n_aliases += 1
        await db.commit()
        run.notes = (run.notes or "") + f" | aliases={n_aliases} | rules={counts['rules']}"
        log.info("ofac_sdn.aliases_upserted", n=n_aliases)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sdn", type=Path, required=True)
    p.add_argument("--add", type=Path, default=None)
    p.add_argument("--alt", type=Path, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.sdn, args.add, args.alt))


if __name__ == "__main__":
    main()
