from __future__ import annotations

from arq.connections import RedisSettings

from app.config import settings
from app.models.registry import load_models
from app.pipeline import versions
from app.telemetry import configure_logging, log
from app.workers.batch_screen import screen_one
from app.workers.embedding_jobs import backfill_sanctions_embeddings
from app.workers.eval_jobs import run_eval_job
from app.workers.refdata_jobs import run_refdata
from app.workers.training_jobs import train_ltr


async def startup(ctx: dict) -> None:
    configure_logging()
    log.info("worker.starting")
    ctx["models"] = load_models()
    # Static version stamp (engine + model hashes), computed once so batch-screened
    # decisions carry the same audit lineage as the sync API path (item 12).
    ctx["versions_static"] = versions.compute_static()
    log.info("worker.ready")


async def shutdown(ctx: dict) -> None:
    log.info("worker.shutting_down")


class WorkerSettings:
    functions = [screen_one, run_refdata, train_ltr, run_eval_job, backfill_sanctions_embeddings]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    # Training builds the LTR dataset by running retrieval against every gold
    # query — that takes several minutes on a non-trivial split. Eval has the
    # same shape. 1h is generous; nothing here is interactive.
    job_timeout = 3600
    keep_result = 3600
