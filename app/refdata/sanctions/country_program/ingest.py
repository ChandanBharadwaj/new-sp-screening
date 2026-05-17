"""Generic ingester for country-specific commodity sanctions programs.

OFAC publishes per-country regulations (31 CFR Part 510 DPRK, 542 Syria, 560 Iran,
515 Cuba, 591/592 Venezuela) that go beyond party lists: sectoral commodity bans,
import prohibitions, licensed exports. The structure is small enough per-country
that operators maintain it as a YAML file; this module ingests one file at a time
and registers as one source per country (IRAN, DPRK, SYRIA, CUBA, VENEZUELA).

YAML schema (see fixtures/iran.example.yaml for a worked example):

    source: IRAN                              # SOURCES key; also used in DB.source
    country_iso: IR
    provenance_url: https://...
    restrictions:
      - description: "Iranian-origin petroleum & petroleum products"
        hs_codes: ["2710"]                    # prefixes ok; will be 6-digit-padded
        restriction_type: blocked
        direction: import_from                # block if origin = country_iso
      - description: "Aircraft & parts exported to Iran"
        hs_codes: ["8802", "8803"]
        restriction_type: licensed
        direction: export_to                  # restrict if destination = country_iso
      - description: "Comprehensive embargo on dual-use goods"
        hs_codes: []                          # empty = match by semantic only
        restriction_type: prohibited
        direction: both

direction: one of `import_from` | `export_to` | `both` (default `export_to`).

USAGE:
    python -m app.refdata.sanctions.country_program.ingest \\
        --file ./data/sanctions/iran.yaml
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import yaml

from app.refdata.common import with_run_logging
from app.refdata.sanctions.common import normalize_codes, upsert_sanctioned_commodities
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


def parse(file: Path) -> tuple[str, str, list[dict]]:
    """Parse a country-program YAML. Returns (source_key, country_iso, rows)."""
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
        # Pad short codes to 6 digits by chapter/heading semantics — `normalize_codes`
        # in sanctions.common already enforces 6-digit minimum, so we left-trim any
        # decoration and accept prefixes by padding with zeros for storage.
        codes = []
        for c in codes_raw:
            s = "".join(ch for ch in str(c) if ch.isdigit())
            if not s:
                continue
            if len(s) < 6:
                s = s + "0" * (6 - len(s))
            codes.append(s)
        codes = normalize_codes(codes)
        direction = (r.get("direction") or "export_to").strip().lower()
        restriction = (r.get("restriction_type") or "blocked").strip().lower()
        rows.append(
            {
                "source_record_id": f"{source_key}-{idx}",
                "description": desc[:2000],
                "hs_codes": codes,
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
        with_hs=sum(1 for r in rows if r["hs_codes"]),
    )
    async with with_run_logging(source_key, notes=f"file={file} country={country_iso}") as (db, run):
        counts = await upsert_sanctioned_commodities(db, rows, source=source_key, run=run)
        run.rows_upserted = counts["sanctioned"]
        run.notes = (run.notes or "") + f" | rules={counts['rules']}"


# Convenience entrypoints — one per SOURCES catalog entry. They all delegate to
# `main_async` with the right file path. The worker dispatcher routes to these.
def _default_file(country_slug: str) -> Path:
    return Path(f"data/sanctions/country_program/{country_slug}.yaml")


async def run_with_default(country_slug: str, file: Path | None = None) -> None:
    """Used by the worker dispatcher when the operator hasn't overridden the path."""
    await main_async(file or _default_file(country_slug))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file", type=Path, required=True)
    args = p.parse_args()
    asyncio.run(main_async(args.file))


def _entrypoint_factory(country_slug: str) -> Any:
    """Returns a (sync) main() pinned to a specific country's default file path."""

    def _main() -> None:
        p = argparse.ArgumentParser()
        p.add_argument("--file", type=Path, default=_default_file(country_slug))
        args = p.parse_args()
        asyncio.run(main_async(args.file))

    return _main


if __name__ == "__main__":
    main()
