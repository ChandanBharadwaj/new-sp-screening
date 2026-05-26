"""Runtime policy/threshold cache (items 4 + 10).

Screening policy lives in Postgres (`inference_threshold`, `policy_parameter`),
not in Python constants, so every value bound to a decision is auditable and can
be changed without a redeploy. This module is the read path:

- `get_policy_snapshot(db)` returns an immutable `PolicySnapshot` of the values
  active *now*, refreshed from the DB at most once per `policy_cache_ttl_s`.
- A request takes one snapshot at the top and uses it throughout, so a mid-request
  policy change can never produce an inconsistent decision (the change applies to
  the next request — exactly the canary semantics in the design doc).
- The TTL poll is the durable hot-reload mechanism. LISTEN/NOTIFY can be layered on
  later to cut propagation latency; it is not required for correctness because the
  poll always converges and NOTIFY is not durable across listener restarts.

`snapshot.version` is stamped onto each decision (`screening_result.versions`) so a
later audit retrieves the exact thresholds that were live when the shipment scored.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InferenceThreshold, PolicyParameter

_TTL_S = 30.0


class PolicySnapshot:
    """Immutable view of the policy/threshold values active at load time."""

    __slots__ = ("_thresholds", "_params", "version", "loaded_at")

    def __init__(
        self,
        thresholds: dict[tuple[str, str], float],
        params: dict[tuple[str, str], Any],
        version: str,
        loaded_at: float,
    ) -> None:
        self._thresholds = thresholds
        self._params = params
        self.version = version
        self.loaded_at = loaded_at

    def threshold(self, pipeline: str, parameter: str, default: float) -> float:
        return self._thresholds.get((pipeline, parameter), default)

    def param(self, scope: str, name: str, default: Any) -> Any:
        return self._params.get((scope, name), default)


async def _load(db: AsyncSession) -> PolicySnapshot:
    th_rows = (
        await db.execute(
            select(
                InferenceThreshold.threshold_id,
                InferenceThreshold.pipeline,
                InferenceThreshold.parameter,
                InferenceThreshold.value,
            ).where(InferenceThreshold.effective_to.is_(None))
        )
    ).all()
    pp_rows = (
        await db.execute(
            select(
                PolicyParameter.param_id,
                PolicyParameter.scope,
                PolicyParameter.name,
                PolicyParameter.value,
            ).where(PolicyParameter.effective_to.is_(None))
        )
    ).all()

    thresholds = {(r.pipeline, r.parameter): float(r.value) for r in th_rows}
    params = {(r.scope, r.name): r.value for r in pp_rows}

    ids = sorted(f"t{r.threshold_id}" for r in th_rows) + sorted(f"p{r.param_id}" for r in pp_rows)
    version = hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:16] if ids else "empty"
    return PolicySnapshot(thresholds, params, version, time.monotonic())


class _Cache:
    def __init__(self) -> None:
        self._snapshot: PolicySnapshot | None = None
        self._lock = asyncio.Lock()

    async def get(self, db: AsyncSession) -> PolicySnapshot:
        snap = self._snapshot
        if snap is not None and (time.monotonic() - snap.loaded_at) < _TTL_S:
            return snap
        async with self._lock:
            # Re-check after acquiring the lock — another coroutine may have refreshed.
            snap = self._snapshot
            if snap is not None and (time.monotonic() - snap.loaded_at) < _TTL_S:
                return snap
            self._snapshot = await _load(db)
            return self._snapshot

    def invalidate(self) -> None:
        self._snapshot = None


_cache = _Cache()


async def get_policy_snapshot(db: AsyncSession) -> PolicySnapshot:
    return await _cache.get(db)


def invalidate_policy_cache() -> None:
    """Force the next get_policy_snapshot to reload (e.g. after an admin edit)."""
    _cache.invalidate()
