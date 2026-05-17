"""OFAC SDN parser tests.

The parser is offline / file-based, so we synthesize tiny CSV fixtures on disk
and check that joins (alt → ent_num, add → ent_num) work and that program tags
map to the right destination ISOs.
"""
from pathlib import Path

from app.refdata.sanctions.ofac_sdn.parser import (
    PROGRAM_TO_ISO,
    SdnRecord,
    _split_programs,
    parse,
)


def _write_sdn(p: Path, rows: list[list[str]]) -> None:
    # No header; OFAC's spec specifies fixed column order.
    p.write_text("\n".join(",".join(f'"{c}"' for c in r) for r in rows), encoding="latin-1")


class TestParse:
    def test_minimal(self, tmp_path: Path) -> None:
        sdn = tmp_path / "sdn.csv"
        _write_sdn(
            sdn,
            [
                # ent_num, name, type, programs, title, call_sign, vessel_type,
                # tonnage, grt, vessel_flag, vessel_owner, remarks
                ["1001", "Some Entity", "entity", "IRAN", "-0-", "-0-", "-0-",
                 "-0-", "-0-", "-0-", "-0-", "-0-"],
            ],
        )
        records = parse(sdn, None, None)
        assert len(records) == 1
        r = records[0]
        assert r.ent_num == "1001"
        assert r.name == "Some Entity"
        assert r.sdn_type == "entity"
        assert r.programs == ["IRAN"]
        assert r.derived_destination_isos == ["IR"]

    def test_aliases_attached(self, tmp_path: Path) -> None:
        sdn = tmp_path / "sdn.csv"
        alt = tmp_path / "alt.csv"
        _write_sdn(
            sdn,
            [["1001", "Some Entity", "entity", "DPRK", "", "", "", "", "", "", "", ""]],
        )
        _write_sdn(
            alt,
            [
                ["1001", "10001", "aka", "AKA Name One", ""],
                ["1001", "10002", "fka", "Former Name", ""],
                ["1001", "10003", "nka", "Now Known As", ""],
            ],
        )
        records = parse(sdn, None, alt)
        assert len(records) == 1
        r = records[0]
        assert len(r.aliases) == 3
        kinds = {a["alias_kind"] for a in r.aliases}
        assert kinds == {"aka", "fka"}  # "nka" maps to "aka"
        assert r.derived_destination_isos == ["KP"]

    def test_addresses_attached(self, tmp_path: Path) -> None:
        sdn = tmp_path / "sdn.csv"
        add = tmp_path / "add.csv"
        _write_sdn(
            sdn,
            [["1001", "Some Entity", "entity", "SDGT", "", "", "", "", "", "", "", ""]],
        )
        _write_sdn(
            add,
            [
                ["1001", "20001", "123 Main", "Tehran", "Iran", ""],
                ["1001", "20002", "5 Side St", "Damascus", "Syria", ""],
            ],
        )
        records = parse(sdn, add, None)
        r = records[0]
        assert r.countries == ["Iran", "Syria"]
        # SDGT is not in PROGRAM_TO_ISO — no derived destination.
        assert r.derived_destination_isos == []

    def test_orphan_alt_is_dropped(self, tmp_path: Path) -> None:
        sdn = tmp_path / "sdn.csv"
        alt = tmp_path / "alt.csv"
        _write_sdn(sdn, [["1001", "X", "entity", "", "", "", "", "", "", "", "", ""]])
        _write_sdn(alt, [["9999", "1", "aka", "Phantom Alias", ""]])
        records = parse(sdn, None, alt)
        assert len(records) == 1
        assert records[0].aliases == []


class TestSplitPrograms:
    def test_semicolon(self) -> None:
        assert _split_programs("IRAN;SDGT") == ["IRAN", "SDGT"]

    def test_comma_fallback(self) -> None:
        assert _split_programs("IRAN,SDGT") == ["IRAN", "SDGT"]

    def test_empty(self) -> None:
        assert _split_programs(None) == []
        assert _split_programs("") == []


def test_program_to_iso_covers_comprehensive_embargoes() -> None:
    # Spot-check the comprehensive embargo set.
    assert PROGRAM_TO_ISO["IRAN"] == "IR"
    assert PROGRAM_TO_ISO["DPRK"] == "KP"
    assert PROGRAM_TO_ISO["SYRIA"] == "SY"
    assert PROGRAM_TO_ISO["CUBA"] == "CU"
    assert PROGRAM_TO_ISO["VENEZUELA"] == "VE"


def test_sdn_record_derived_isos_dedup() -> None:
    r = SdnRecord(ent_num="1", name="x", sdn_type="entity", programs=["IRAN", "iran"])
    assert r.derived_destination_isos == ["IR"]
