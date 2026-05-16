from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_batch, routes_hs, routes_results, routes_screen, routes_status
from app.config import settings
from app.models.registry import load_models
from app.telemetry import configure_logging, log


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("app.starting", engine_version=settings.engine_version)
    app.state.models = load_models()
    log.info("app.ready")
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "engine_version": settings.engine_version}
