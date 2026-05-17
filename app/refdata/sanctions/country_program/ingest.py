"""Generic ingester for country-specific commodity sanctions programs.

OFAC publishes per-country regulations (31 CFR Part 510 DPRK, 542 Syria, 560 Iran,
515 Cuba, 591/592 Venezuela) that go beyond party lists: sectoral commodity bans,
import prohibitions, licensed exports. The structure is small enough per-country
that operators maintain it as a YAML file; this module ingests one file at a time
and registers as one source per country (IRAN, DPRK, SYRIA, CUBA, VENEZUELA).

YAML schema (see data/sanctions/country_program/iran.yaml for a worked example):

    source: IRAN                              # SOURCES key; also used in DB.source
    country_iso: IR
    provenance_url: https://...
    restrictions:
      - description: "Iranian-origin petroleum & petroleum products"
        hs_codes: ["2710"]                    # chapter (2-digit) or heading (4-digit)
                                              # prefixes are expanded against the loaded
                                              # HS taxonomy to all 6-digit subheadings
                                              # at ingest time (requires HTS to be loaded
                                              # first; SOURCES declares depends_on=["HTS"]).
      - description: "Aircraft & parts exported to Iran"
        hs_codes: ["8802", "8803"]
        restriction_type: licensed
        direction: export_to                  # restrict if destination = country_iso
      - description: "Comprehensive embargo on dual-use goods"
        hs_codes: []                          # empty = match by semantic only
        restriction_type: prohibited
        direction: both

direction: one of `import_from` | `export_to` | `both` (default `export_to`).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import yaml

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import (
    expand_rows_in_place,
    upsert_sanctioned_commodities,
)
from app.telemetry import configure_logging, log

VALID_DIRECTIONS = ("import_from", "export_to", "both")


def _country_rules(country_iso: str, direction: str, restriction: str) -> list[dict]:
    """Translate (country, direction) into CountryRule row(s)."""
    direction = direction or "export_to"
    if direction not in VALID_DIRECTIONS:
        raise ValueError(f"invalid direction {direction!r}, expected one of {VALID_DIRECTIONS}")

    if direction == "import_from":
        return [{"origin_iso": country_iso, "destination_iso": None, "restriction_type": restriction}]
    if direction == "export_to":
        return [{"origin_iso": None, "destination_iso": country_iso, "restriction_type": restriction}]
    # both
    return [
        {"origin_iso": country_iso, "destination_iso": None, "restriction_type": restriction},
        {"origin_iso": None, "destination_iso": country_iso, "restriction_type": restriction},
    ]


def _clean_code(raw: object) -> str | None:
    """Strip non-digit decoration; return the digits-only form, or None if empty."""
    s = "".join(ch for ch in str(raw) if ch.isdigit())
    return s or None


def parse(file: Path) -> tuple[str, str, list[dict]]:
    """Parse a country-program YAML. Returns (source_key, country_iso, rows).

    HS code prefixes are kept as-is (e.g. "2710" stays "2710"). Expansion to 6-digit
    subheadings happens in `app.refdata.sanctions.common.expand_hs_prefixes` against
    the live `hs_code` table — kept out of `parse()` so this function stays pure and
    testable without a DB.
    """
    with file.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}

    source_key = (doc.get("source") or "").strip().upper()
    country_iso = (doc.get("country_iso") or "").strip().upper()
    provenance = doc.get("provenance_url") or ""
    restrictions = doc.get("restrictions") or []

    if not source_key:
        raise ValueError(f"{file}: missing required `source` key")
    if not country_iso or len(country_iso) != 2:
        raise ValueError(f"{file}: `country_iso` must be a 2-letter ISO code")
    if not isinstance(restrictions, list):
        raise ValueError(f"{file}: `restrictions` must be a list")

    rows: list[dict] = []
    for idx, r in enumerate(restrictions):
        desc = (r.get("description") or "").strip()
        if not desc:
            log.warning("country_program.skip_no_desc", file=str(file), idx=idx)
            continue
        codes_raw = r.get("hs_codes") or []
        if not isinstance(codes_raw, list):
            raise ValueError(f"{file}[{idx}]: hs_codes must be a list")
        codes: list[str] = []
        for c in codes_raw:
            cleaned = _clean_code(c)
            if cleaned is None:
                continue
            # Validate length: 2, 4, or 6 digits only. Anything else is a typo.
            if len(cleaned) not in (2, 4, 6):
                raise ValueError(
                    f"{file}[{idx}]: hs_code {c!r} must be a 2-, 4-, or 6-digit code"
                )
            codes.append(cleaned)
        direction = (r.get("direction") or "export_to").strip().lower()
        restriction = (r.get("restriction_type") or "blocked").strip().lower()
        rows.append(
            {
                "source_record_id": f"{source_key}-{idx}",
                "description": desc[:2000],
                "hs_codes": codes,  # prefixes kept here; expansion happens later
                "restriction_type": restriction,
                "provenance_url": provenance or None,
                "country_rules": _country_rules(country_iso, direction, restriction),
            }
        )

    return source_key, country_iso, rows


async def main_async(file: Path) -> None:
    configure_logging()
    log.info("country_program.parsing", file=str(file))
    source_key, country_iso, rows = parse(file)
    log.info(
        "country_program.parsed",
        source=source_key,
        country=country_iso,
        n=len(rows),
    )
    async with with_run_logging(source_key, notes=f"file={file} country={country_iso}") as (db, run):
        # Expand prefixes inside the run so the warning logs are tied to this RefdataRun.
        await expand_rows_in_place(db, rows)
        log.info(
            "country_program.expanded",
            source=source_key,
            with_hs=sum(1 for r in rows if r["hs_codes"]),
            total_codes=sum(len(r["hs_codes"]) for r in rows),
        )
        counts = await upsert_sanctioned_commodities(db, rows, source=source_key, run=run)
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main_async(args.file))


if __name__ == "__main__":
    main()
