"""Parse OFAC SDN list files (sdn.csv, add.csv, alt.csv).

OFAC publishes the SDN list as three CSVs with no header row. Column layouts are
fixed by Treasury's spec at https://sanctionslist.ofac.treas.gov/Home/SdnList.

sdn.csv  : ent_num, name, type, programs, title, call_sign, vessel_type,
           tonnage, grt, vessel_flag, vessel_owner, remarks
add.csv  : ent_num, add_num, address, city_state_zip, country, add_remarks
alt.csv  : ent_num, alt_num, alt_type, alt_name, alt_remarks

The parser is offline / pure-Python; the ingester (`ingest.py`) consumes its
output and writes to the DB.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

# OFAC's column orderings (zero-indexed, no header).
SDN_COLS = (
    "ent_num", "name", "type", "programs", "title", "call_sign",
    "vessel_type", "tonnage", "grt", "vessel_flag", "vessel_owner", "remarks",
)
ADD_COLS = ("ent_num", "add_num", "address", "city_state_zip", "country", "add_remarks")
ALT_COLS = ("ent_num", "alt_num", "alt_type", "alt_name", "alt_remarks")

# Map OFAC program tags to a destination ISO-2 we'd block-on-default for that record.
# Conservative — only the comprehensive country embargoes; sector-specific programs (SDGT,
# NARCO, etc.) intentionally do not auto-attach a country (semantic match still applies).
PROGRAM_TO_ISO: dict[str, str] = {
    "IRAN": "IR",
    "DPRK": "KP",
    "SYRIA": "SY",
    "CUBA": "CU",
    "VENEZUELA": "VE",
    # Russia is partial (sectoral) — operators should rely on EU_RUSSIA / dedicated lists.
}


@dataclass
class SdnRecord:
    ent_num: str
    name: str
    sdn_type: str  # individual | entity | vessel | aircraft
    programs: list[str]
    title: str | None = None
    remarks: str | None = None
    addresses: list[dict] = field(default_factory=list)
    aliases: list[dict] = field(default_factory=list)

    @property
    def countries(self) -> list[str]:
        seen: list[str] = []
        for a in self.addresses:
            c = (a.get("country") or "").strip()
            if c and c not in seen:
                seen.append(c)
        return seen

    @property
    def derived_destination_isos(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for p in self.programs:
            iso = PROGRAM_TO_ISO.get(p.strip().upper())
            if iso and iso not in seen:
                seen.add(iso)
                out.append(iso)
        return out


def _read_ofac_csv(path: Path, cols: tuple[str, ...]) -> list[dict]:
    """OFAC CSVs use `-0-` as a null sentinel; convert to None."""
    rows: list[dict] = []
    with path.open("r", encoding="latin-1", newline="") as fh:
        reader = csv.reader(fh)
        for raw in reader:
            if not raw:
                continue
            padded = raw + [""] * (len(cols) - len(raw))
            r = dict(zip(cols, padded, strict=False))
            for k, v in list(r.items()):
                v = (v or "").strip()
                r[k] = None if v == "-0-" else v
            rows.append(r)
    return rows


def _split_programs(s: str | None) -> list[str]:
    if not s:
        return []
    # OFAC programs are semicolon-delimited inside the CSV cell; some files use comma.
    parts = [p.strip() for p in s.replace(",", ";").split(";")]
    return [p for p in parts if p]


def parse(sdn_path: Path, add_path: Path | None, alt_path: Path | None) -> list[SdnRecord]:
    """Parse the three SDN CSV files, joining add/alt rows onto their parent ent_num."""
    sdn_rows = _read_ofac_csv(sdn_path, SDN_COLS)

    records: dict[str, SdnRecord] = {}
    for r in sdn_rows:
        ent = r.get("ent_num")
        name = r.get("name")
        if not ent or not name:
            continue
        records[ent] = SdnRecord(
            ent_num=ent,
            name=name,
            sdn_type=(r.get("type") or "").lower(),
            programs=_split_programs(r.get("programs")),
            title=r.get("title"),
            remarks=r.get("remarks"),
        )

    if add_path and add_path.exists():
        for r in _read_ofac_csv(add_path, ADD_COLS):
            rec = records.get(r.get("ent_num") or "")
            if rec is None:
                continue
            rec.addresses.append(
                {
                    "address": r.get("address"),
                    "city_state_zip": r.get("city_state_zip"),
                    "country": r.get("country"),
                }
            )

    if alt_path and alt_path.exists():
        for r in _read_ofac_csv(alt_path, ALT_COLS):
            rec = records.get(r.get("ent_num") or "")
            if rec is None:
                continue
            alt_name = r.get("alt_name")
            if not alt_name:
                continue
            kind = (r.get("alt_type") or "").lower()
            # Map OFAC alt_type ("aka", "fka", "nka") to our alias_kind taxonomy.
            if kind in ("aka", "fka"):
                alias_kind = kind
            elif kind == "nka":
                alias_kind = "aka"  # "now known as" — treat as primary alias
            else:
                alias_kind = "aka"
            rec.aliases.append({"alias": alt_name, "alias_kind": alias_kind})

    return list(records.values())
