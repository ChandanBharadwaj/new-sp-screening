"""Ingest the US Munitions List (USML) from 22 CFR § 121 (ITAR).

DDTC does not publish a structured feed for the USML; operators export the list
from the eCFR or maintain a curated CSV/XLSX with one row per controlled article.

Expected columns (case-insensitive; first match wins):
    usml_category   : I-XXI (Roman) or 1-21 (Arabic)
    paragraph       : optional, e.g. "(a)(1)"
    description     : required
    hs_codes        : optional comma/semicolon-separated 6-digit codes
    restriction_type: optional; default "export_controlled"

INPUT:
    --file ./data/sanctions/itar/usml.csv

USAGE:
    python -m app.refdata.sanctions.itar.ingest --file ./data/sanctions/itar/usml.csv
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pandas as pd

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import (
    expand_rows_in_place,
    normalize_codes,
    upsert_sanctioned_commodities,
)
from app.telemetry import configure_logging, log

PROVENANCE = "https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M/part-121"

CATEGORY_KEYS = ("usml_category", "category", "cat", "usml")
PARAGRAPH_KEYS = ("paragraph", "para", "subparagraph")
DESCRIPTION_KEYS = ("description", "article", "item description", "controlled article")
HS_KEYS = ("hs_codes", "hs code", "hs", "schedule b", "tariff")
RESTRICTION_KEYS = ("restriction_type", "restriction", "control_type")


def _pick(row: pd.Series, keys: tuple[str, ...]) -> str | None:
    for col in row.index:
        if str(col).strip().lower() in keys:
            v = row[col]
            if pd.isna(v):
                return None
            return str(v).strip()
    return None


def _split_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").replace("/", ",").split(",")]
    return [p for p in parts if p]


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _parse(path: Path) -> list[dict]:
    df = _read_table(path)
    rows: list[dict] = []
    for idx, row in df.iterrows():
        cat = _pick(row, CATEGORY_KEYS)
        desc = _pick(row, DESCRIPTION_KEYS)
        if not cat or not desc:
            continue
        para = _pick(row, PARAGRAPH_KEYS)
        record_id = f"USML-{cat}{para or ''}-{idx}"
        hs_raw = _pick(row, HS_KEYS)
        hs_codes = normalize_codes(_split_codes(hs_raw))
        restriction = _pick(row, RESTRICTION_KEYS) or "export_controlled"

        # ITAR articles default to a blanket export-from-US control with no
        # destination filter (semantic match + commodity HS overlap still
        # gates which records actually surface for a given shipment).
        rows.append(
            {
                "source_record_id": record_id,
                "description": f"USML {cat}{(' ' + para) if para else ''}: {desc}"[:2000],
                "hs_codes": hs_codes,
                "restriction_type": restriction,
                "provenance_url": PROVENANCE,
                "country_rules": [
                    {
                        "origin_iso": "US",
                        "destination_iso": None,
                        "restriction_type": restriction,
                    }
                ],
            }
        )
    return rows


async def main_async(file: Path) -> None:
    configure_logging()
    log.info("itar.parsing", file=str(file))
    items = _parse(file)
    log.info("itar.parsed", n=len(items), with_hs=sum(1 for r in items if r["hs_codes"]))
    async with with_run_logging("ITAR_USML", notes=f"file={file}") as (db, run):
        await expand_rows_in_place(db, items)
        counts = await upsert_sanctioned_commodities(db, items, source="ITAR_USML", run=run)
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main_async(args.file))


if __name__ == "__main__":
    main()
