"""Adapter wrapping the real screening pipeline as the eval Classifier interface."""
from __future__ import annotations

from app.db.session import SessionLocal
from app.models.registry import load_models
from app.pipeline.orchestrator import run_screen


class Classifier:
    name = "pipeline"

    def __init__(self) -> None:
        self.models = load_models()

    async def classify(self, text: str) -> list[str]:
        async with SessionLocal() as db:
            payload = await run_screen(
                db=db,
                models=self.models,
                commodity_text=text,
                cargo_text=None,
            )
        return [c["hs_code"] for c in payload["hs_classification"]["top_candidates"]]
