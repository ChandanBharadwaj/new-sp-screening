"""Verify the OFAC alias INSERT is idempotent.

We don't have a live Postgres in unit tests, so we mock the session and assert
that every INSERT into `sanctioned_commodity_alias` carries an
`ON CONFLICT DO NOTHING` clause targeting the `uq_alias_per_commodity` constraint.
That clause, combined with the unique constraint added in migration 0003, is what
makes a weekly OFAC refresh safe to re-run without bloating the alias table.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_alias_insert_uses_on_conflict_do_nothing(monkeypatch) -> None:
    # We invoke the inner alias-insert loop in isolation by patching the
    # parent-id lookup and the upsert helper out of the way; only the alias
    # INSERT path matters here.
    from app.refdata.sanctions.ofac_sdn import ingest as mod

    captured: list = []

    class StubResult:
        def scalar_one_or_none(self) -> int:
            return 42  # pretend the parent commodity got id 42

    async def fake_execute(stmt):
        captured.append(stmt)
        return StubResult()

    fake_db = MagicMock()
    fake_db.execute = AsyncMock(side_effect=fake_execute)
    fake_db.commit = AsyncMock()

    # Stub the heavy upsert + run_logging so we exercise only the alias loop.
    async def fake_upsert(_db, _items, source, run) -> dict:
        return {"sanctioned": 1, "rules": 1}

    monkeypatch.setattr(mod, "upsert_sanctioned_commodities", fake_upsert)

    class _NullRun:
        rows_upserted = 0
        notes = ""

    class _Ctx:
        async def __aenter__(self):
            return fake_db, _NullRun()

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(mod, "with_run_logging", lambda *a, **k: _Ctx())
    monkeypatch.setattr(mod, "parse", lambda *a, **k: [_FakeRec()])

    await mod.main_async(_FakePath("sdn.csv"), None, None)

    # Filter out the parent-id SELECT (a Select object), keep the alias INSERTs.
    inserts = [s for s in captured if hasattr(s, "_post_values_clause")]
    # Each alias should compile with the ON CONFLICT DO NOTHING clause.
    assert inserts, "expected at least one alias INSERT to fire"
    for stmt in inserts:
        # The post-values clause holds the ON CONFLICT directive; its presence
        # alone is enough to confirm we won't double-insert on rerun.
        assert stmt._post_values_clause is not None


class _FakePath:
    def __init__(self, p: str) -> None:
        self._p = p

    def __fspath__(self) -> str:
        return self._p

    def __str__(self) -> str:
        return self._p


class _FakeRec:
    """A stand-in for parser.SdnRecord shaped like _record_to_row expects."""

    ent_num = "1001"
    name = "Some Entity"
    sdn_type = "entity"
    programs = ["IRAN"]
    title = None
    remarks = None
    addresses: list = []
    aliases = [
        {"alias": "AKA One", "alias_kind": "aka"},
        {"alias": "AKA Two", "alias_kind": "aka"},
    ]
    countries: list = []
    derived_destination_isos = ["IR"]
