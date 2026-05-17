"""HS prefix expansion in app/refdata/sanctions/common.py.

Pure logic test — we stub the HsCode lookup so this runs without a database.

The bug being guarded against: BIS_CCL / EU_DUAL_USE / EU_RUSSIA / ITAR
ingesters used to drop 2/4-digit HS prefixes during normalize_codes (or, with
the new normalize_codes that keeps them, would otherwise persist non-matching
strings in sanctioned_commodity.hs_codes). The shipment classifier emits
6-digit HS codes — `&&` array equality is exact, so without expansion the
structured-overlap query never matches a 4-digit prefix.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.refdata.sanctions.common import (
    expand_hs_prefixes,
    expand_rows_in_place,
    normalize_codes,
)


def test_normalize_codes_keeps_short_prefixes() -> None:
    # 8-digit CN gets truncated to 6; 4-digit kept; 2-digit kept; junk dropped.
    out = normalize_codes(["85423100", "8542", "85", "x", ""])
    assert out == ["854231", "8542", "85"]


def test_normalize_codes_dedupes() -> None:
    assert normalize_codes(["8542", "8542", "85"]) == ["8542", "85"]


@pytest.mark.asyncio
async def test_expand_hs_prefixes_fans_out_to_6_digit() -> None:
    fake_db = MagicMock()

    def make_result(rows):
        scalars = MagicMock()
        scalars.all.return_value = rows
        r = MagicMock()
        r.scalars.return_value = scalars
        return r

    # The helper queries hs_code with .like("8542%") for the 4-digit input,
    # then .like("85%") for the 2-digit input. Return canned 6-digit rows.
    fake_db.execute = AsyncMock(
        side_effect=[
            make_result(["854231", "854232", "854233"]),
            make_result(["854231", "854310"]),
        ]
    )

    out = await expand_hs_prefixes(fake_db, ["8542", "85"])
    # Already-6-digit codes (none here) would pass through; 4-digit + 2-digit
    # expansions are unioned and sorted.
    assert out == sorted({"854231", "854232", "854233", "854310"})


@pytest.mark.asyncio
async def test_expand_hs_prefixes_passes_through_6_digit() -> None:
    fake_db = MagicMock()
    fake_db.execute = AsyncMock()
    out = await expand_hs_prefixes(fake_db, ["854231", "854232"])
    assert out == ["854231", "854232"]
    # No DB call needed for already-6-digit codes.
    fake_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_expand_hs_prefixes_drops_unresolvable_prefix() -> None:
    fake_db = MagicMock()

    def make_result(rows):
        scalars = MagicMock()
        scalars.all.return_value = rows
        r = MagicMock()
        r.scalars.return_value = scalars
        return r

    # The prefix isn't loaded — return empty rows; the helper logs and drops it.
    fake_db.execute = AsyncMock(return_value=make_result([]))
    out = await expand_hs_prefixes(fake_db, ["9999"])
    assert out == []


@pytest.mark.asyncio
async def test_expand_rows_in_place_mutates_each_row() -> None:
    fake_db = MagicMock()

    def make_result(rows):
        scalars = MagicMock()
        scalars.all.return_value = rows
        r = MagicMock()
        r.scalars.return_value = scalars
        return r

    fake_db.execute = AsyncMock(return_value=make_result(["854231"]))

    rows = [{"hs_codes": ["8542"]}, {"hs_codes": []}]
    await expand_rows_in_place(fake_db, rows)
    assert rows[0]["hs_codes"] == ["854231"]
    assert rows[1]["hs_codes"] == []
