"""Ingest the US BIS Commerce Control List (15 CFR Part 774 Supp. 1) + BIS HS-ECCN crosswalk.

The CCL itself is published in the Federal Register as text. BIS additionally publishes
an "HS-ECCN" crosswalk Excel that ties Schedule B/HS to ECCNs; operators download both
and feed them in.

INPUT:
  --ccl-file        : CSV/XLSX export of the CCL with columns ECCN, description, control reasons.
  --crosswalk-file  : BIS HS-ECCN crosswalk XLSX.

USAGE:
    python -m app.refdata.sanctions.bis_ccl.ingest \\
        --ccl-file ./data/sanctions/bis_ccl.csv \\
        --crosswalk-file ./data/sanctions/bis_hs_eccn_crosswalk.xlsx
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

PROVENANCE_CCL = "https://www.bis.doc.gov/index.php/regulations/commerce-control-list-ccl"
PROVENANCE_CROSSWALK = "https://www.bis.doc.gov/index.php/all-articles/2-uncategorized/146-correlation-table"

ECCN_KEYS = ("eccn",)
DESCRIPTION_KEYS = ("description", "heading", "item description")
HS_KEYS = ("hs code", "hs", "schedule b", "scheduleb", "cn code")
COUNTRY_KEYS = ("country", "destination", "country group")


def _pick(row: pd.Series, keys: tuple[str, ...]) -> str | None:
    for col in row.index:
        if str(col).strip().lower() in keys:
            v = row[col]
            if pd.isna(v):
                return None
            return str(v).strip()
    return None


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path)
    return pd.read_csv(path)


def _load_crosswalk(path: Path) -> dict[str, list[str]]:
    df = _read_table(path)
    cw: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        eccn = _pick(row, ECCN_KEYS)
        hs_raw = _pick(row, HS_KEYS)
        if not eccn or not hs_raw:
            continue
        parts = [p.strip() for p in hs_raw.replace(";", ",").replace("/", ",").split(",")]
        codes = normalize_codes(parts)
        if codes:
            cw.setdefault(eccn.strip(), []).extend(codes)
    return cw


async def main_async(ccl_file: Path, crosswalk_file: Path | None) -> None:
    configure_logging()
    log.info("bis_ccl.parsing", ccl=str(ccl_file), crosswalk=str(crosswalk_file))
    cw = _load_crosswalk(crosswalk_file) if crosswalk_file else {}
    log.info("bis_ccl.crosswalk_loaded", n_eccn=len(cw))

    df = _read_table(ccl_file)
    items: list[dict] = []
    for _, row in df.iterrows():
        eccn = _pick(row, ECCN_KEYS)
        desc = _pick(row, DESCRIPTION_KEYS)
        if not eccn or not desc:
            continue
        items.append(
            {
                "source_record_id": eccn,
                "description": desc[:2000],
                "hs_codes": cw.get(eccn, []),
                "restriction_type": "licensed",
                "provenance_url": PROVENANCE_CCL,
                "country_rules": [{"origin_iso": "US", "destination_iso": None, "restriction_type": "licensed"}],
            }
        )
    log.info("bis_ccl.parsed", n=len(items), with_hs=sum(1 for r in items if r["hs_codes"]))

    async with with_run_logging("BIS_CCL", notes=f"ccl={ccl_file} crosswalk={crosswalk_file}") as (
        db,
        run,
    ):
        # Fan out HS-2/HS-4 prefixes against the live taxonomy so the structured
        # overlap join in app/pipeline/sanctions.py matches 6-digit shipments.
        await expand_rows_in_place(db, items)
        counts = await upsert_sanctioned_commodities(db, items, source="BIS_CCL", run=run)
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--ccl-file", type=Path, required=True)
    p.add_argument("--crosswalk-file", type=Path, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.ccl_file, args.crosswalk_file))


if __name__ == "__main__":
    main()
