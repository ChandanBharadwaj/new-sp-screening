"""Ingest EU Russia sanctions annexes from Council Regulation (EU) 833/2014.

Each annex (XVII = luxury goods, XVIII = oil products, XXI = advanced tech, etc.) lists
CN codes inline; we treat each row as a sanctioned_commodity and attach a country_rule
scoped to the appropriate direction (export ban to RU vs import ban from RU).

INPUT: operator-downloaded XLSX/CSV exports of the published annexes.

USAGE:
    python -m app.refdata.sanctions.eu_russia.ingest --file ./data/sanctions/eu_russia_annex_xvii.xlsx --direction export
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pandas as pd

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import normalize_codes, upsert_sanctioned_commodities
from app.telemetry import configure_logging, log

PROVENANCE = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833"

CN_KEYS = ("cn code", "cn", "hs code", "hs", "tariff code", "code")
DESCRIPTION_KEYS = ("description", "goods description", "item description", "product")


def _pick(row: pd.Series, keys: tuple[str, ...]) -> str | None:
    for col in row.index:
        if str(col).strip().lower() in keys:
            v = row[col]
            if pd.isna(v):
                return None
            return str(v).strip()
    return None


def _split_cn(raw: str) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").replace("/", ",").split(",")]
    return [p for p in parts if p]


def _parse(path: Path, annex_label: str) -> list[dict]:
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    rows: list[dict] = []
    for idx, row in df.iterrows():
        cn = _pick(row, CN_KEYS)
        desc = _pick(row, DESCRIPTION_KEYS)
        if not cn or not desc:
            continue
        hs_codes = normalize_codes(_split_cn(cn))
        if not hs_codes:
            continue
        rows.append(
            {
                "source_record_id": f"{annex_label}-{idx}",
                "description": desc[:2000],
                "hs_codes": hs_codes,
                "restriction_type": "prohibited",
                "provenance_url": PROVENANCE,
            }
        )
    return rows


async def main_async(file: Path, direction: str, annex_label: str) -> None:
    configure_logging()
    log.info("eu_russia.parsing", file=str(file), direction=direction)
    items = _parse(file, annex_label)
    # Attach country rules based on the direction the annex covers.
    if direction == "export":  # EU bans EXPORTS to RU
        cr = {"origin_iso": None, "destination_iso": "RU", "restriction_type": "prohibited"}
    elif direction == "import":  # EU bans IMPORTS from RU
        cr = {"origin_iso": "RU", "destination_iso": None, "restriction_type": "prohibited"}
    else:
        cr = {"origin_iso": None, "destination_iso": None, "restriction_type": "prohibited"}
    for it in items:
        it["country_rules"] = [cr]

    log.info("eu_russia.parsed", n=len(items))
    async with with_run_logging("EU_RUSSIA", notes=f"file={file} annex={annex_label} dir={direction}") as (
        db,
        run,
    ):
        counts = await upsert_sanctioned_commodities(db, items, source="EU_RUSSIA")
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--direction", choices=("export", "import", "both"), required=True)
    p.add_argument("--annex", type=str, default="XVII", help="annex label for source_record_id prefix")
    args = p.parse_args()
    asyncio.run(main_async(args.file, args.direction, args.annex))


if __name__ == "__main__":
    main()
