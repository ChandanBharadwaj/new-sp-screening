from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_admin,
    routes_batch,
    routes_dashboards,
    routes_data,
    routes_eval,
    routes_feedback,
    routes_hs,
    routes_jobs,
    routes_results,
    routes_rules,
    routes_sanctions,
    routes_screen,
    routes_status,
    routes_thresholds,
    routes_training,
)
from app.config import settings
from app.models.registry import load_models
from app.pipeline import versions
from app.telemetry import configure_logging, log


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("app.starting", engine_version=settings.engine_version)
    app.state.models = load_models()
    # Cache the static version snapshot (engine + model hashes) once at startup so
    # every screening can stamp it without re-hashing the LTR file per request.
    app.state.versions_static = versions.compute_static()
    log.info("app.ready", versions=app.state.versions_static)
    yield
    log.info("app.shutting_down")


app = FastAPI(
    title="Commodity Screening Engine",
    version=settings.engine_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_screen.router)
app.include_router(routes_batch.router)
app.include_router(routes_results.router)
app.include_router(routes_hs.router)
app.include_router(routes_status.router)
app.include_router(routes_sanctions.router)
app.include_router(routes_rules.router)
app.include_router(routes_feedback.router)
app.include_router(routes_dashboards.router)
app.include_router(routes_admin.router)
app.include_router(routes_data.router)
app.include_router(routes_training.router)
app.include_router(routes_eval.router)
app.include_router(routes_thresholds.router)
app.include_router(routes_jobs.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine_version": settings.engine_version}
