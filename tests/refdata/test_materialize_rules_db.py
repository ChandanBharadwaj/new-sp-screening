"""DB-backed integration tests for `materialize_for_source`.

Skip when DATABASE_URL is unset (mirrors the existing pattern in
`tests/conftest.py`). These exercise:
  - the partial unique index on (created_by, name) for idempotent re-runs
  - orphan soft-deactivation
  - the enabled=False short-circuit

The embedder dependency is patched out to keep the test off the network.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import delete, select

from app.db.models import (
    CountryRule,
    SanctionedCommodity,
    SanctionsRuleConfig,
    ScreeningRule,
)
from app.refdata.sanctions import materialize_rules


class _FakeEmbedder:
    """Stand-in for app.models.embedder.Embedder so we never touch real models."""

    def encode_batch(self, phrases: Iterable[str]) -> list[np.ndarray]:
        # 384-dim zero vector per the EMBED_DIM constant in db/models.py.
        return [np.zeros(384, dtype=np.float32) for _ in phrases]


@pytest.fixture
def fake_embedder():
    with patch.object(
        materialize_rules, "lazy_embedder", return_value=_FakeEmbedder()
    ):
        yield


async def _seed_commodity(
    db, *, source: str, source_record_id: str, description: str
) -> int:
    row = SanctionedCommodity(
        source=source,
        source_record_id=source_record_id,
        description=description,
        hs_codes=[],
    )
    db.add(row)
    await db.flush()
    return row.id


async def _seed_country_rule(
    db,
    *,
    commodity_id: int,
    origin: str | None,
    destination: str | None,
    restriction_type: str = "blocked",
    conditions: dict[str, Any] | None = None,
) -> None:
    db.add(
        CountryRule(
            origin_iso=origin,
            destination_iso=destination,
            sanctioned_commodity_id=commodity_id,
            restriction_type=restriction_type,
            conditions=conditions,
            active=True,
        )
    )


async def _enable_source(
    db,
    source: str,
    *,
    threshold: float = 0.55,
    strategy: str = "split_lists",
) -> None:
    cfg = (
        await db.execute(
            select(SanctionsRuleConfig).where(SanctionsRuleConfig.source == source)
        )
    ).scalar_one_or_none()
    if cfg is None:
        db.add(
            SanctionsRuleConfig(
                source=source,
                enabled=True,
                default_threshold=threshold,
                phrase_strategy=strategy,
            )
        )
    else:
        cfg.enabled = True
        cfg.default_threshold = threshold
        cfg.phrase_strategy = strategy


async def _cleanup(db, source: str) -> None:
    """Remove any rows this test created so we leave the dev DB clean."""
    await db.execute(
        delete(ScreeningRule).where(ScreeningRule.created_by == f"sanctions_source:{source}")
    )
    sc_ids = (
        await db.execute(select(SanctionedCommodity.id).where(SanctionedCommodity.source == source))
    ).scalars().all()
    if sc_ids:
        await db.execute(delete(CountryRule).where(CountryRule.sanctioned_commodity_id.in_(sc_ids)))
        await db.execute(delete(SanctionedCommodity).where(SanctionedCommodity.id.in_(sc_ids)))
    await db.execute(delete(SanctionsRuleConfig).where(SanctionsRuleConfig.source == source))
    await db.commit()


TEST_SOURCE = "TEST_MATERIALIZE"


async def test_disabled_source_is_noop(db, fake_embedder):
    try:
        await _cleanup(db, TEST_SOURCE)
        cid = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-1", description="oil"
        )
        await _seed_country_rule(db, commodity_id=cid, origin="ZZ", destination=None)
        await db.commit()

        # No config row at all → no-op.
        counts = await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        assert counts == {"created": 0, "updated": 0, "deactivated": 0, "kept": 0}

        rows = (
            await db.execute(
                select(ScreeningRule).where(
                    ScreeningRule.created_by == f"sanctions_source:{TEST_SOURCE}"
                )
            )
        ).scalars().all()
        assert rows == []
    finally:
        await _cleanup(db, TEST_SOURCE)


async def test_first_run_creates_rules_second_run_updates_idempotently(db, fake_embedder):
    try:
        await _cleanup(db, TEST_SOURCE)
        await _enable_source(db, TEST_SOURCE)
        cid_a = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-A", description="rum, tobacco"
        )
        cid_b = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-B", description="petroleum products"
        )
        await _seed_country_rule(db, commodity_id=cid_a, origin="ZZ", destination=None)
        await _seed_country_rule(db, commodity_id=cid_b, origin=None, destination="ZZ")
        await db.commit()

        counts1 = await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        assert counts1["applied"] == 2
        assert counts1["created"] == 2
        assert counts1["updated"] == 0
        assert counts1["deactivated"] == 0

        # Second run with no changes — same names UPSERT to themselves, no orphans.
        counts2 = await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        assert counts2["applied"] == 2
        assert counts2["created"] == 0
        assert counts2["updated"] == 2
        assert counts2["deactivated"] == 0

        rows = (
            await db.execute(
                select(ScreeningRule).where(
                    ScreeningRule.created_by == f"sanctions_source:{TEST_SOURCE}"
                )
            )
        ).scalars().all()
        assert len(rows) == 2
        assert all(r.active for r in rows)
        # Multi-phrase descriptions produce phrase_group, single ones don't.
        by_phrase = {r.phrase: r for r in rows}
        assert by_phrase["rum, tobacco"].phrase_group is not None
        assert by_phrase["rum, tobacco"].phrase_group["mode"] == "any_of"
        assert by_phrase["petroleum products"].phrase_group is None
    finally:
        await _cleanup(db, TEST_SOURCE)


async def test_orphaned_rule_is_deactivated_after_commodity_removed(db, fake_embedder):
    try:
        await _cleanup(db, TEST_SOURCE)
        await _enable_source(db, TEST_SOURCE)
        cid_a = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-A", description="oil"
        )
        cid_b = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-B", description="gold"
        )
        await _seed_country_rule(db, commodity_id=cid_a, origin="ZZ", destination=None)
        await _seed_country_rule(db, commodity_id=cid_b, origin="ZZ", destination=None)
        await db.commit()

        await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        # Now remove commodity B and re-run; that row's materialized rule should
        # be soft-deactivated, not deleted.
        await db.execute(delete(CountryRule).where(CountryRule.sanctioned_commodity_id == cid_b))
        await db.execute(delete(SanctionedCommodity).where(SanctionedCommodity.id == cid_b))
        await db.commit()

        counts = await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        assert counts["deactivated"] == 1

        rows = (
            await db.execute(
                select(ScreeningRule).where(
                    ScreeningRule.created_by == f"sanctions_source:{TEST_SOURCE}"
                )
            )
        ).scalars().all()
        assert len(rows) == 2  # one active, one deactivated; nothing deleted
        actives = [r for r in rows if r.active]
        inactives = [r for r in rows if not r.active]
        assert len(actives) == 1 and len(inactives) == 1
        assert actives[0].phrase == "oil"
        assert inactives[0].phrase == "gold"
    finally:
        await _cleanup(db, TEST_SOURCE)


async def test_direction_both_creates_two_distinct_scoped_rules(db, fake_embedder):
    try:
        await _cleanup(db, TEST_SOURCE)
        await _enable_source(db, TEST_SOURCE)
        cid = await _seed_commodity(
            db, source=TEST_SOURCE, source_record_id="T-Both", description="dual-use chemicals"
        )
        # The country_program ingester emits two CountryRule rows for direction=both.
        await _seed_country_rule(db, commodity_id=cid, origin="ZZ", destination=None)
        await _seed_country_rule(db, commodity_id=cid, origin=None, destination="ZZ")
        await db.commit()

        counts = await materialize_rules.materialize_for_source(db, TEST_SOURCE)
        assert counts["applied"] == 2

        rows = (
            await db.execute(
                select(ScreeningRule)
                .where(ScreeningRule.created_by == f"sanctions_source:{TEST_SOURCE}")
                .where(ScreeningRule.active.is_(True))
            )
        ).scalars().all()
        scopes = {(r.origin_iso, r.destination_iso) for r in rows}
        assert scopes == {("ZZ", None), (None, "ZZ")}
    finally:
        await _cleanup(db, TEST_SOURCE)
