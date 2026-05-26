"""arq job: run_refdata(source, params).

Dispatches to the right ingester module's `main_async`. The worker loads the
model registry once at startup so each ingest re-uses the same Embedder /
Reranker / GLiNER / LightGBM instance (cf. app.workers.arq_app).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.db.session import SessionLocal
from app.refdata.cross import ingest as cross_ingest
from app.refdata.cross import scraper as cross_scraper
from app.refdata.gold import assemble as gold_assemble
from app.refdata.hs_entities import build as hs_entities
from app.refdata.hts import ingest as hts_ingest
from app.refdata.keyword_lists import ingest as keyword_list_ingest
from app.refdata.sanctions import materialize_rules
from app.refdata.sanctions.bis_ccl import ingest as bis_ingest
from app.refdata.sanctions.country_program import ingest as country_ingest
from app.refdata.sanctions.eu_dual_use import ingest as eu_du
from app.refdata.sanctions.eu_russia import ingest as eu_ru
from app.refdata.sanctions.itar import ingest as itar_ingest
from app.refdata.schedule_b import ingest as sb_ingest
from app.refdata.wco import ingest as wco_ingest
from app.telemetry import log

KEYWORD_LIST_PREFIX = keyword_list_ingest.SOURCE_PREFIX  # "KW:"

# Keys that route through a sanctions ingester and produce sanctioned_commodity
# rows. After ingest we re-materialize ScreeningRule rows from these (gated by
# sanctions_rule_config.enabled — no-op when off).
# Commodity-focused sources only. Party screening (OFAC SDN, EU/UN consolidated
# financial-sanctions party lists) is out of scope for this engine and is handled
# by a separate dedicated party-screening system — see README and docs/sanctions-sources.md.
SANCTIONS_SOURCES = frozenset(
    {
        "EU_DUAL_USE",
        "EU_RUSSIA",
        "BIS_CCL",
        "ITAR_USML",
        "IRAN",
        "DPRK",
        "SYRIA",
        "CUBA",
        "VENEZUELA",
    }
)


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
        elif source == "WCO":
            await wco_ingest.main_async(
                _pathy(params.get("file")) or Path("data/taxonomy/wco_hs_2022.xlsx")
            )
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
        elif source == "ITAR_USML":
            await itar_ingest.main_async(
                _pathy(params.get("file")) or Path("data/sanctions/itar/usml.csv")
            )
        elif source in ("IRAN", "DPRK", "SYRIA", "CUBA", "VENEZUELA"):
            # All country-program sources route through the generic YAML ingester.
            # Default file path follows the SOURCES catalog: <slug>.yaml.
            default = Path(f"data/sanctions/country_program/{source.lower()}.yaml")
            await country_ingest.main_async(_pathy(params.get("file")) or default)
        elif source.startswith(KEYWORD_LIST_PREFIX):
            # Operator-authored keyword list. The portion after the prefix is the
            # manifest's `name`; the ingester re-loads scope/threshold from the DB.
            list_name = source[len(KEYWORD_LIST_PREFIX):]
            await keyword_list_ingest.main_async(list_name=list_name)
        else:
            return {"status": "unknown_source", "source": source}
        # Materialize ScreeningRule rows for sanctions sources whose
        # sanctions_rule_config.enabled is true. This is a cheap no-op for
        # disabled sources (one indexed SELECT on sanctions_rule_config).
        # Keyword-list sources auto-enable materialization at ingest time, so
        # they fall through this path the same way as OFAC/EU/etc.
        materialized: dict | None = None
        is_keyword_list = source.startswith(KEYWORD_LIST_PREFIX)
        if source in SANCTIONS_SOURCES or is_keyword_list:
            try:
                async with SessionLocal() as db:
                    materialized = await materialize_rules.maybe_materialize_after_ingest(
                        db, source
                    )
            except Exception as me:  # noqa: BLE001 — never let materialization mask ingest success
                log.error("materialize_rules.post_ingest_failed", source=source, error=str(me))
        return {"status": "ok", "source": source, "materialized": materialized}
    except Exception as e:
        log.error("refdata_job.failed", source=source, error=str(e))
        return {"status": "failed", "source": source, "error": str(e)}
