"""Ingest EU Dual-Use Annex I (Council Reg 2021/821, as periodically updated).

Annex I categorizes dual-use goods by EU-specific control codes (e.g., 1A001, 5A002).
The EU publishes the Annex as an XLSX/PDF on EUR-Lex. An accompanying CN/HS crosswalk
gives 6-digit HS codes per item where available.

INPUT: a path to the official Annex I XLSX (operator-downloaded from EUR-Lex).
       Optionally a separate CN crosswalk XLSX.

USAGE:
    python -m app.refdata.sanctions.eu_dual_use.ingest --file ./data/sanctions/eu_dual_use_annex_i.xlsx
    python -m app.refdata.sanctions.eu_dual_use.ingest --file ... --crosswalk ./data/sanctions/cn_crosswalk.xlsx
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import pandas as pd

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import normalize_codes, upsert_sanctioned_commodities
from app.telemetry import configure_logging, log

PROVENANCE = "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02021R0821"

# Common column header aliases across published versions
CONTROL_CODE_KEYS = ("control code", "control_code", "eu code", "category", "item")
DESCRIPTION_KEYS = ("description", "item description", "name")
CN_KEYS = ("cn code", "hs code", "tariff code", "cn", "hs")


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


def _load_crosswalk(path: Path | None) -> dict[str, list[str]]:
    if path is None or not path.exists():
        return {}
    df = pd.read_excel(path)
    cw: dict[str, list[str]] = {}
    for _, row in df.iterrows():
        control = _pick(row, CONTROL_CODE_KEYS)
        cn_raw = _pick(row, CN_KEYS)
        if not control or not cn_raw:
            continue
        cw.setdefault(control, []).extend(_split_cn(cn_raw))
    return cw


def _parse_annex(path: Path, crosswalk: dict[str, list[str]]) -> list[dict]:
    df = pd.read_excel(path)
    rows: list[dict] = []
    for _, row in df.iterrows():
        control = _pick(row, CONTROL_CODE_KEYS)
        description = _pick(row, DESCRIPTION_KEYS)
        if not control or not description:
            continue
        cn_inline = _pick(row, CN_KEYS)
        cn_codes: list[str] = []
        if cn_inline:
            cn_codes.extend(_split_cn(cn_inline))
        cn_codes.extend(crosswalk.get(control, []))
        hs_codes = normalize_codes(cn_codes)
        rows.append(
            {
                "source_record_id": control,
                "description": description[:2000],
                "hs_codes": hs_codes,
                "restriction_type": "licensed",
                "provenance_url": PROVENANCE,
                "country_rules": [{"origin_iso": None, "destination_iso": None, "restriction_type": "licensed"}],
            }
        )
    return rows


async def main_async(file: Path, crosswalk_path: Path | None) -> None:
    configure_logging()
    log.info("eu_dual_use.parsing", file=str(file))
    crosswalk = _load_crosswalk(crosswalk_path)
    items = _parse_annex(file, crosswalk)
    log.info("eu_dual_use.parsed", n=len(items), with_hs=sum(1 for r in items if r["hs_codes"]))

    async with with_run_logging("EU_DUAL_USE", notes=f"file={file}") as (db, run):
        counts = await upsert_sanctioned_commodities(db, items, source="EU_DUAL_USE")
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--crosswalk", type=Path, default=None)
    args = p.parse_args()
    asyncio.run(main_async(args.file, args.crosswalk))


if __name__ == "__main__":
    main()
