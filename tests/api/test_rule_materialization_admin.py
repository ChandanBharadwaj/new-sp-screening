"""Tests for the three /api/v1/admin/rule-materialization handlers.

Skip when DATABASE_URL is unset. The materializer's heavy lifting is covered in
`tests/refdata/test_materialize_rules_db.py`; here we exercise validation,
upsert behavior, and that GET reports the right counts.

Handlers are invoked directly rather than through FastAPI's ASGI app to avoid
the app's startup lifespan loading ML models on disk.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.api.routes_admin import (
    RuleMaterializationConfigIn,
    list_rule_materialization,
    run_rule_materialization,
    update_rule_materialization,
)
from app.db.models import SanctionedCommodity, SanctionsRuleConfig, ScreeningRule
from app.refdata.sanctions import materialize_rules


class _FakeEmbedder:
    def encode_batch(self, phrases):
        return [np.zeros(384, dtype=np.float32) for _ in phrases]


@pytest.fixture
def fake_embedder():
    with patch.object(materialize_rules, "lazy_embedder", return_value=_FakeEmbedder()):
        yield


async def _cleanup(db, source: str) -> None:
    await db.execute(
        delete(ScreeningRule).where(ScreeningRule.created_by == f"sanctions_source:{source}")
    )
    await db.execute(delete(SanctionsRuleConfig).where(SanctionsRuleConfig.source == source))
    await db.execute(delete(SanctionedCommodity).where(SanctionedCommodity.source == source))
    await db.commit()


async def test_list_returns_one_item_per_sanctions_source(db):
    body = await list_rule_materialization(db)
    assert "items" in body
    sources = {it["source"] for it in body["items"]}
    # The 5 country programs are sanctions sources — every one should appear.
    assert {"IRAN", "DPRK", "SYRIA", "CUBA", "VENEZUELA"}.issubset(sources)
    for it in body["items"]:
        assert "label" in it
        assert "enabled" in it
        assert "active_rules" in it
        assert isinstance(it["active_rules"], int)


async def test_put_rejects_unknown_source(db):
    with pytest.raises(HTTPException) as exc:
        await update_rule_materialization(
            "NOT_A_REAL_SOURCE", RuleMaterializationConfigIn(enabled=True), db
        )
    assert exc.value.status_code == 404


async def test_put_rejects_out_of_range_threshold(db):
    with pytest.raises(HTTPException) as exc:
        await update_rule_materialization(
            "IRAN", RuleMaterializationConfigIn(default_threshold=1.5), db
        )
    assert exc.value.status_code == 400


async def test_put_rejects_invalid_strategy(db):
    with pytest.raises(HTTPException) as exc:
        await update_rule_materialization(
            "IRAN", RuleMaterializationConfigIn(phrase_strategy="bogus"), db
        )
    assert exc.value.status_code == 400


async def test_put_creates_then_updates_config(db):
    try:
        await _cleanup(db, "IRAN")
        # Create
        body = await update_rule_materialization(
            "IRAN",
            RuleMaterializationConfigIn(
                enabled=True, default_threshold=0.6, phrase_strategy="with_aliases"
            ),
            db,
        )
        assert body["enabled"] is True
        assert body["default_threshold"] == 0.6
        assert body["phrase_strategy"] == "with_aliases"

        # Update only one field — others persist.
        body = await update_rule_materialization(
            "IRAN", RuleMaterializationConfigIn(enabled=False), db
        )
        assert body["enabled"] is False
        assert body["default_threshold"] == 0.6
        assert body["phrase_strategy"] == "with_aliases"
    finally:
        await _cleanup(db, "IRAN")


async def test_run_endpoint_materializes_for_enabled_source(db, fake_embedder):
    source = "IRAN"
    try:
        await _cleanup(db, source)
        # Seed a sanctioned_commodity row for IRAN.
        db.add(
            SanctionedCommodity(
                source=source,
                source_record_id="IRAN-MAT-TEST",
                description="Iranian crude oil",
                hs_codes=[],
            )
        )
        await db.commit()

        # Enable the source.
        await update_rule_materialization(
            source, RuleMaterializationConfigIn(enabled=True), db
        )

        # Trigger materialization on-demand.
        body = await run_rule_materialization(source, db)
        assert body["source"] == source
        assert body["applied"] >= 1

        # GET now reflects the count.
        listing = await list_rule_materialization(db)
        items = {it["source"]: it for it in listing["items"]}
        assert items[source]["active_rules"] >= 1
    finally:
        await _cleanup(db, source)


async def test_run_endpoint_rejects_unknown_source(db):
    with pytest.raises(HTTPException) as exc:
        await run_rule_materialization("NOPE", db)
    assert exc.value.status_code == 404
