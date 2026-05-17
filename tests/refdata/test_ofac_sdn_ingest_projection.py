"""Projection of SdnRecord → upsert dict (no DB)."""
from app.refdata.sanctions.ofac_sdn.ingest import _record_to_row
from app.refdata.sanctions.ofac_sdn.parser import SdnRecord


def test_projection_includes_program_country_rule() -> None:
    rec = SdnRecord(
        ent_num="1001",
        name="Some Entity",
        sdn_type="entity",
        programs=["IRAN"],
        aliases=[{"alias": "AKA Name", "alias_kind": "aka"}],
    )
    row = _record_to_row(rec)
    assert row["source_record_id"] == "1001"
    assert row["restriction_type"] == "blocked"
    assert row["hs_codes"] == []
    assert "Some Entity" in row["description"]
    assert "IRAN" in row["description"]
    # Country rule derived from program tag.
    assert row["country_rules"] == [
        {"origin_iso": None, "destination_iso": "IR", "restriction_type": "blocked"}
    ]
    assert row["_aliases"] == [{"alias": "AKA Name", "alias_kind": "aka"}]


def test_projection_no_country_for_non_embargo_program() -> None:
    rec = SdnRecord(
        ent_num="1002",
        name="Sanctioned Drug Lord",
        sdn_type="individual",
        programs=["NARCO"],
    )
    row = _record_to_row(rec)
    assert row["country_rules"] == []


def test_projection_truncates_long_description() -> None:
    rec = SdnRecord(
        ent_num="1003",
        name="X" * 3000,
        sdn_type="entity",
        programs=[],
    )
    row = _record_to_row(rec)
    assert len(row["description"]) <= 2000
