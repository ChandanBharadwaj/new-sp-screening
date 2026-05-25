"""Admin endpoint tests for keyword-list manifests.

Skip when DATABASE_URL is unset. Calls handlers directly (no FastAPI lifespan)
to keep model loading out of the test path.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete

from app.api.routes_admin import (
    KeywordListConfigIn,
    delete_keyword_list,
    list_keyword_lists,
    upload_keyword_list_csv,
    upsert_keyword_list,
)
from app.db.models import KeywordList, SanctionedCommodity, SanctionsRuleConfig, ScreeningRule
from app.refdata.keyword_lists import ingest as kl_ingest


class _FakeEmbedder:
    def encode_batch(self, phrases):
        return [np.zeros(384, dtype=np.float32) for _ in phrases]


@pytest.fixture
def fake_embedder():
    from app.refdata.sanctions import common as sanctions_common
    from app.refdata.sanctions import materialize_rules

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


async def test_put_rejects_invalid_name() -> None:
    with pytest.raises(HTTPException) as exc:
        await upsert_keyword_list("Bad Name With Spaces", KeywordListConfigIn(), None)
    assert exc.value.status_code == 400


async def test_put_rejects_too_long_name() -> None:
    # 32 - len('KW:') = 29; 30 chars must fail.
    long = "a" * 30
    with pytest.raises(HTTPException) as exc:
        await upsert_keyword_list(long, KeywordListConfigIn(), None)
    assert exc.value.status_code == 400


async def test_put_rejects_invalid_direction(db) -> None:
    with pytest.raises(HTTPException) as exc:
        await upsert_keyword_list(
            "anything", KeywordListConfigIn(direction="sideways"), db
        )
    assert exc.value.status_code == 400


async def test_put_rejects_out_of_range_threshold(db) -> None:
    with pytest.raises(HTTPException) as exc:
        await upsert_keyword_list(
            "anything", KeywordListConfigIn(default_threshold=2.0), db
        )
    assert exc.value.status_code == 400


async def test_put_creates_then_updates_manifest(db) -> None:
    list_name = "admin_create_test"
    try:
        await _cleanup(db, list_name)
        body = await upsert_keyword_list(
            list_name,
            KeywordListConfigIn(
                label="Test",
                destination_iso="IR",
                direction="export_to",
                default_threshold=0.6,
            ),
            db,
        )
        assert body["name"] == list_name
        assert body["destination_iso"] == "IR"
        assert body["direction"] == "export_to"
        assert body["default_threshold"] == 0.6
        assert body["active"] is True
        assert body["source_key"] == "KW:admin_create_test"

        # Update one field — others stick.
        body = await upsert_keyword_list(
            list_name, KeywordListConfigIn(active=False), db
        )
        assert body["active"] is False
        assert body["default_threshold"] == 0.6
        assert body["destination_iso"] == "IR"
    finally:
        await _cleanup(db, list_name)


async def test_upload_rejects_unknown_list(db) -> None:
    csv = UploadFile(filename="x.csv", file=io.BytesIO(b"keywords\nfoo\n"))
    with pytest.raises(HTTPException) as exc:
        await upload_keyword_list_csv("no_such_list", csv, db)
    assert exc.value.status_code == 404


async def test_upload_writes_file_and_sets_source_file(db, tmp_path: Path) -> None:
    list_name = "admin_upload_test"
    try:
        await _cleanup(db, list_name)
        await upsert_keyword_list(list_name, KeywordListConfigIn(), db)
        csv_bytes = b"keywords\nfoo\nbar\nbaz\n"
        csv = UploadFile(filename="x.csv", file=io.BytesIO(csv_bytes))
        result = await upload_keyword_list_csv(list_name, csv, db)
        assert result["name"] == list_name
        assert result["size_bytes"] == len(csv_bytes)
        assert Path(result["path"]).exists()

        listing = await list_keyword_lists(db)
        names = {it["name"] for it in listing["items"]}
        assert list_name in names
        item = next(it for it in listing["items"] if it["name"] == list_name)
        assert item["file_present"] is True
    finally:
        await _cleanup(db, list_name)
        # Remove the on-disk file we created.
        from app.api.routes_admin import KEYWORD_LIST_DATA_ROOT

        fp = KEYWORD_LIST_DATA_ROOT / f"{list_name}.csv"
        if fp.exists():
            fp.unlink()


async def test_delete_removes_manifest_and_data(db, fake_embedder, tmp_path: Path) -> None:
    """End-to-end: create manifest, upload CSV, ingest, then delete and verify nothing remains."""
    list_name = "admin_delete_test"
    try:
        await _cleanup(db, list_name)
        await upsert_keyword_list(list_name, KeywordListConfigIn(), db)
        csv = UploadFile(filename="x.csv", file=io.BytesIO(b"keywords\nfoo\nbar\n"))
        await upload_keyword_list_csv(list_name, csv, db)

        await kl_ingest.main_async(list_name=list_name)
        from app.refdata.sanctions import materialize_rules

        src = kl_ingest.source_key(list_name)
        await materialize_rules.materialize_for_source(db, src)

        # Now delete via the admin endpoint.
        result = await delete_keyword_list(list_name, db)
        assert result["deleted"] is True

        # Manifest gone.
        listing = await list_keyword_lists(db)
        assert list_name not in {it["name"] for it in listing["items"]}

        # Sanctioned commodities for this source gone.
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        n_sanc = (
            await db.execute(
                sa_select(func.count())
                .select_from(SanctionedCommodity)
                .where(SanctionedCommodity.source == src)
            )
        ).scalar_one()
        assert n_sanc == 0
    finally:
        await _cleanup(db, list_name)
        from app.api.routes_admin import KEYWORD_LIST_DATA_ROOT

        fp = KEYWORD_LIST_DATA_ROOT / f"{list_name}.csv"
        if fp.exists():
            fp.unlink()
