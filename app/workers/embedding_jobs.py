"""Embedding backfill for the embedder-swap procedure (item 1).

Regenerates `sanctioned_commodity.embedding_v2` with a target model so a new
embedding generation can be parity-gated and cut over without silent recall loss.
Only current rows (`sys_to IS NULL`) are backfilled — the live screening set.

Concurrency-safe: a Postgres advisory lock prevents cron-launched and manual
backfills from fighting; rows are claimed with FOR UPDATE SKIP LOCKED so multiple
workers don't trample. Throttled to one BLAS thread per worker.
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.embedder import Embedder  # noqa: E402
from app.telemetry import log  # noqa: E402

_ADVISORY_KEY = "emb_backfill_sanctions"
_BATCH = 512


def _vec_literal(vec) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


async def backfill_sanctions_embeddings(ctx: dict, target_model: str) -> dict:
    """Fill embedding_v2 for current sanctioned_commodity rows using `target_model`.

    Idempotent and resumable: only touches rows where embedding_v2 IS NULL. Returns
    a status dict; re-run until `remaining == 0`, then run the parity gate.
    """
    embedder = Embedder(model_name=target_model)
    total = 0
    async with SessionLocal() as db:
        got_lock = (
            await db.execute(text("SELECT pg_try_advisory_lock(hashtext(:k))"), {"k": _ADVISORY_KEY})
        ).scalar_one()
        if not got_lock:
            log.info("embedding_backfill.lock_held", target_model=target_model)
            return {"status": "lock_held", "backfilled": 0}
        try:
            while True:
                rows = (
                    await db.execute(
                        text(
                            """
                            SELECT id, description
                            FROM sanctioned_commodity
                            WHERE embedding_v2 IS NULL AND sys_to IS NULL
                            ORDER BY id
                            LIMIT :n
                            FOR UPDATE SKIP LOCKED
                            """
                        ),
                        {"n": _BATCH},
                    )
                ).all()
                if not rows:
                    break
                vectors = embedder.encode_batch([r.description for r in rows])
                for r, v in zip(rows, vectors, strict=True):
                    await db.execute(
                        text(
                            "UPDATE sanctioned_commodity "
                            "SET embedding_v2 = CAST(:vec AS vector), embedding_v2_model = :m "
                            "WHERE id = :id"
                        ),
                        {"vec": _vec_literal(v), "m": target_model, "id": r.id},
                    )
                await db.commit()
                total += len(rows)
                log.info("embedding_backfill.progress", target_model=target_model, backfilled=total)
            remaining = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM sanctioned_commodity "
                        "WHERE embedding_v2 IS NULL AND sys_to IS NULL"
                    )
                )
            ).scalar_one()
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(hashtext(:k))"), {"k": _ADVISORY_KEY})
            await db.commit()
    log.info("embedding_backfill.done", target_model=target_model, backfilled=total, remaining=int(remaining))
    return {"status": "ok", "backfilled": total, "remaining": int(remaining)}
