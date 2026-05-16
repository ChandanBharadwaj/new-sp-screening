from __future__ import annotations

from arq.connections import RedisSettings

from app.config import settings
from app.models.registry import load_models
from app.telemetry import configure_logging, log
from app.workers.batch_screen import screen_one
from app.workers.refdata_jobs import run_refdata


async def startup(ctx: dict) -> None:
    configure_logging()
    log.info("worker.starting")
    ctx["models"] = load_models()
    log.info("worker.ready")


async def shutdown(ctx: dict) -> None:
    log.info("worker.shutting_down")


class WorkerSettings:
    functions = [screen_one, run_refdata]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 4
    job_timeout = 60
    keep_result = 3600
