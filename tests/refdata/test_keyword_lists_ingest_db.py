"""DB-backed tests for keyword-list ingest end-to-end.

Skip when DATABASE_URL is unset (mirrors the existing pattern). Exercises:
  - Full ingest path: CSV → sanctioned_commodity → country_rule → screening_rule
  - Materialization auto-enabled for KW:* sources
  - Re-upload with one keyword removed soft-deactivates that rule
  - Empty CSV deletes everything for the source

The embedder is patched out (zero vectors) so the test never touches the real
sentence-transformers download.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import delete, select

from app.db.models import (
    CountryRule,
    KeywordList,
    SanctionedCommodity,
    SanctionsRuleConfig,
    ScreeningRule,
)
from app.refdata.keyword_lists import ingest as kl_ingest
from app.refdata.sanctions import common as sanctions_common
from app.refdata.sanctions import materialize_rules


class _FakeEmbedder:
    def encode_batch(self, phrases: Iterable[str]) -> list[np.ndarray]:
        return [np.zeros(384, dtype=np.float32) for _ in phrases]


@pytest.fixture
def fake_embedder():
    # Both the sanctions ingest helper and the materializer pull the embedder
    # through `lazy_embedder()` — patch both call sites.
    with (
        patch.object(sanctions_common, "lazy_embedder", return_value=_FakeEmbedder()),
        patch.object(materialize_rules, "lazy_embedder", return_value=_FakeEmbedder()),
    ):
        yield


async def _cleanup(db, list_name: str) -> None:
    src = kl_ingest.source_key(list_name)
    await db.execute(
        delete(ScreeningRule).where(ScreeningRule.created_by == f"sanctions_source:{src}")
    )
    await db.execute(delete(SanctionsRuleConfig).where(SanctionsRuleConfig.source == src))
    await db.execute(delete(SanctionedCommodity).where(SanctionedCommodity.source == src))
    await db.execute(delete(KeywordList).where(KeywordList.name == list_name))
    await db.commit()


async def _make_manifest(db, list_name: str, tmp_path: Path, **overrides) -> Path:
    csv_path = tmp_path / f"{list_name}.csv"
    db.add(
        KeywordList(
            name=list_name,
            label=overrides.get("label", f"Test {list_name}"),
            origin_iso=overrides.get("origin_iso"),
            destination_iso=overrides.get("destination_iso"),
            direction=overrides.get("direction"),
            restriction_type=overrides.get("restriction_type", "watchlist"),
            default_threshold=overrides.get("default_threshold", 0.5),
            active=True,
            source_file=str(csv_path),
        )
    )
    await db.commit()
    return csv_path


async def test_full_ingest_creates_commodities_rules_and_country_rules(
    db, fake_embedder, tmp_path: Path
) -> None:
    list_name = "seafood_test"
    try:
        await _cleanup(db, list_name)
        csv_path = await _make_manifest(
            db, list_name, tmp_path,
            destination_iso="IR", direction="export_to",
        )
        csv_path.write_text(
            "keywords\nyellowfin tuna\nbluefin tuna\ncaviar\n", encoding="utf-8"
        )

        await kl_ingest.main_async(list_name=list_name)
        # Trigger materialization explicitly — refdata_jobs.run_refdata fires it after
        # ingest in production, but main_async() alone doesn't.
        await materialize_rules.materialize_for_source(db, kl_ingest.source_key(list_name))

        src = kl_ingest.source_key(list_name)
        sanc_count = (
            await db.execute(
                select(SanctionedCommodity).where(SanctionedCommodity.source == src)
            )
        ).scalars().all()
        assert len(sanc_count) == 3

        country_rules = (
            await db.execute(
                select(CountryRule).join(
                    SanctionedCommodity,
                    SanctionedCommodity.id == CountryRule.sanctioned_commodity_id,
                ).where(SanctionedCommodity.source == src)
            )
        ).scalars().all()
        assert len(country_rules) == 3
        assert all(cr.destination_iso == "IR" for cr in country_rules)
        assert all(cr.origin_iso is None for cr in country_rules)

        # Materialization auto-enabled.
        cfg = (
            await db.execute(
                select(SanctionsRuleConfig).where(SanctionsRuleConfig.source == src)
            )
        ).scalar_one()
        assert cfg.enabled is True

        # Three active screening rules (one per keyword).
        rules = (
            await db.execute(
                select(ScreeningRule).where(
                    ScreeningRule.created_by == f"sanctions_source:{src}",
                    ScreeningRule.active.is_(True),
                )
            )
        ).scalars().all()
        assert len(rules) == 3
        phrases = {r.phrase for r in rules}
        assert phrases == {"yellowfin tuna", "bluefin tuna", "caviar"}

        # Manifest bookkeeping updated.
        manifest = (
            await db.execute(select(KeywordList).where(KeywordList.name == list_name))
        ).scalar_one()
        assert manifest.row_count == 3
        assert manifest.last_ingested_at is not None
    finally:
        await _cleanup(db, list_name)


async def test_re_upload_removes_orphan_and_deactivates_rule(
    db, fake_embedder, tmp_path: Path
) -> None:
    list_name = "seafood_orphan_test"
    try:
        await _cleanup(db, list_name)
        csv_path = await _make_manifest(db, list_name, tmp_path)
        csv_path.write_text("keywords\nshrimp\nlobster\ncrab\n", encoding="utf-8")

        await kl_ingest.main_async(list_name=list_name)
        await materialize_rules.materialize_for_source(db, kl_ingest.source_key(list_name))

        src = kl_ingest.source_key(list_name)
        # Sanity: 3 commodities, 3 active rules.
        n_sanc = len(
            (
                await db.execute(
                    select(SanctionedCommodity).where(SanctionedCommodity.source == src)
                )
            ).scalars().all()
        )
        assert n_sanc == 3

        # Re-upload with one keyword removed.
        csv_path.write_text("keywords\nshrimp\ncrab\n", encoding="utf-8")
        await kl_ingest.main_async(list_name=list_name)
        await materialize_rules.materialize_for_source(db, src)

        # Sanctioned commodities: down to 2.
        remaining = (
            await db.execute(
                select(SanctionedCommodity).where(SanctionedCommodity.source == src)
            )
        ).scalars().all()
        assert {r.description for r in remaining} == {"shrimp", "crab"}

        # Active screening rules: down to 2; the lobster rule soft-deactivated.
        all_rules = (
            await db.execute(
                select(ScreeningRule).where(
                    ScreeningRule.created_by == f"sanctions_source:{src}"
                )
            )
        ).scalars().all()
        active_phrases = {r.phrase for r in all_rules if r.active}
        inactive_phrases = {r.phrase for r in all_rules if not r.active}
        assert active_phrases == {"shrimp", "crab"}
        assert "lobster" in inactive_phrases
    finally:
        await _cleanup(db, list_name)


async def test_edit_keyword_in_place_updates_content(
    db, fake_embedder, tmp_path: Path
) -> None:
    """Editing a keyword (same row position) must replace the old commodity, not
    silently keep it. Regression for the positional-id + ON CONFLICT DO NOTHING bug."""
    list_name = "seafood_edit_test"
    try:
        await _cleanup(db, list_name)
        csv_path = await _make_manifest(db, list_name, tmp_path)
        csv_path.write_text("keywords\ntuna\ncod\nshrimp\n", encoding="utf-8")
        await kl_ingest.main_async(list_name=list_name)

        src = kl_ingest.source_key(list_name)
        descs_v1 = {
            r.description
            for r in (
                await db.execute(
                    select(SanctionedCommodity).where(SanctionedCommodity.source == src)
                )
            ).scalars().all()
        }
        assert descs_v1 == {"tuna", "cod", "shrimp"}

        # Edit row 1 in place: cod -> salmon.
        csv_path.write_text("keywords\ntuna\nsalmon\nshrimp\n", encoding="utf-8")
        await kl_ingest.main_async(list_name=list_name)

        descs_v2 = {
            r.description
            for r in (
                await db.execute(
                    select(SanctionedCommodity).where(SanctionedCommodity.source == src)
                )
            ).scalars().all()
        }
        # "cod" gone, "salmon" present — the edit landed.
        assert descs_v2 == {"tuna", "salmon", "shrimp"}
    finally:
        await _cleanup(db, list_name)


async def test_missing_manifest_raises(db, fake_embedder) -> None:
    with pytest.raises(ValueError, match="has no manifest row"):
        await kl_ingest.main_async(list_name="does_not_exist_anywhere")


async def test_manifest_without_source_file_raises(
    db, fake_embedder, tmp_path: Path
) -> None:
    list_name = "no_file_test"
    try:
        await _cleanup(db, list_name)
        db.add(
            KeywordList(name=list_name, default_threshold=0.5, source_file=None)
        )
        await db.commit()
        with pytest.raises(ValueError, match="has no source_file set"):
            await kl_ingest.main_async(list_name=list_name)
    finally:
        await _cleanup(db, list_name)
