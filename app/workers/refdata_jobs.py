"""arq job: run_refdata(source, params).

Dispatches to the right ingester module's `main_async`. The worker loads the
model registry once at startup so each ingest re-uses the same Embedder /
Reranker / GLiNER / LightGBM instance (cf. app.workers.arq_app).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.refdata.cross import ingest as cross_ingest
from app.refdata.cross import scraper as cross_scraper
from app.refdata.gold import assemble as gold_assemble
from app.refdata.hs_entities import build as hs_entities
from app.refdata.hts import ingest as hts_ingest
from app.refdata.sanctions.bis_ccl import ingest as bis_ingest
from app.refdata.sanctions.eu_consolidated import ingest as eu_cons
from app.refdata.sanctions.eu_dual_use import ingest as eu_du
from app.refdata.sanctions.eu_russia import ingest as eu_ru
from app.refdata.sanctions.un import ingest as un_ingest
from app.refdata.schedule_b import ingest as sb_ingest
from app.telemetry import log


def _pathy(p: str | None) -> Path | None:
    return Path(p) if p else None


async def run_refdata(ctx: dict, source: str, params: dict[str, Any]) -> dict:
    """Worker entrypoint. Returns a small status dict; UI polls
    /api/v1/status/refdata for actual progress (rows_upserted / status)."""
    params = params or {}
    log.info("refdata_job.start", source=source, params=params)
    try:
        if source == "HTS":
            await hts_ingest.main_async(year=params.get("year"), file=_pathy(params.get("file")))
        elif source == "ScheduleB":
            csv_path = _pathy(params.get("file")) or Path("data/schedule_b/schedule_b.csv")
            await sb_ingest.main_async(csv_path)
        elif source == "CROSS":
            # Two-step: scrape, then ingest. Operator usually wants both.
            await cross_scraper.main_async(
                max_rulings=int(params.get("max_rulings", 5000)),
                query=params.get("query", "*"),
                rps=float(params.get("rps", 1.0)),
            )
            await cross_ingest.main_async(_pathy(params.get("html_dir")) or Path("data/cross_raw/rulings"))
        elif source == "CROSS_INGEST_ONLY":
            await cross_ingest.main_async(_pathy(params.get("html_dir")) or Path("data/cross_raw/rulings"))
        elif source == "HsEntityIndex":
            await hs_entities.main_async(level=params.get("level"), limit=params.get("limit"))
        elif source == "GoldAssembly":
            await gold_assemble.main_async(
                target=int(params.get("target", 1200)),
                per_chapter=int(params.get("per_chapter", 30)),
                sources=[s.strip() for s in str(params.get("sources", "cross_ruling,schedule_b")).split(",")],
                train_frac=float(params.get("train_frac", 0.70)),
                dev_frac=float(params.get("dev_frac", 0.15)),
                seed=int(params.get("seed", 42)),
            )
        elif source == "EU_DUAL_USE":
            await eu_du.main_async(
                _pathy(params.get("file")) or Path("data/sanctions/eu_dual_use_annex_i.xlsx"),
                _pathy(params.get("crosswalk")),
            )
        elif source == "EU_RUSSIA":
            await eu_ru.main_async(
                _pathy(params.get("file")) or Path("data/sanctions/eu_russia_annex.xlsx"),
                direction=params.get("direction", "export"),
                annex_label=params.get("annex", "XVII"),
            )
        elif source == "BIS_CCL":
            await bis_ingest.main_async(
                _pathy(params.get("ccl_file")) or Path("data/sanctions/bis_ccl.csv"),
                _pathy(params.get("crosswalk_file")),
            )
        elif source == "UN_CONSOLIDATED":
            await un_ingest.main_async(_pathy(params.get("file")), download=True)
        elif source == "EU_CONSOLIDATED":
            await eu_cons.main_async(
                _pathy(params.get("file")) or Path("data/sanctions/eu_consolidated.xml")
            )
        else:
            return {"status": "unknown_source", "source": source}
        return {"status": "ok", "source": source}
    except Exception as e:
        log.error("refdata_job.failed", source=source, error=str(e))
        return {"status": "failed", "source": source, "error": str(e)}
