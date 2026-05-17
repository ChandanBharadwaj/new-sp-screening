"""Admin endpoints — control refdata ingestion and reset from the UI.

There is no CLI in v2 — every ingest can be triggered with one POST request from
the Admin page. Files that the publisher does not auto-serve (Schedule B CSV,
EU Dual-Use XLSX, BIS CCL files, EU Consolidated XML) are uploaded through this
API and persisted under `./data/<source>/` so subsequent re-ingest is one click.

Reset truncates every ingested data table but leaves uploaded source files on
disk and leaves operator-authored `screening_rule` rows alone unless
`include_rules=true` is passed.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated, Any

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.config import settings
from app.db.models import (
    HsCode,
    HsTrainingExample,
    RefdataRun,
    SanctionedCommodity,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

DATA_ROOT = Path("data")

# Canonical source catalog — single source of truth for the Admin UI.
# `files` describes uploads the operator must provide. `auto_download` means the
# ingester fetches the source from the publisher.
SOURCES: list[dict[str, Any]] = [
    {
        "source": "HTS",
        "label": "US Harmonized Tariff Schedule",
        "kind": "taxonomy",
        "auto_download": True,
        "files": [],
        "params_schema": {"year": {"type": "int", "default": None, "required": False}},
        "depends_on": [],
        "publisher_url": "https://hts.usitc.gov/",
    },
    {
        "source": "ScheduleB",
        "label": "US Census Schedule B",
        "kind": "labels",
        "auto_download": False,
        "files": [
            {
                "key": "csv",
                "label": "Schedule B CSV",
                "path": "data/schedule_b/schedule_b.csv",
                "accept": ".csv",
            }
        ],
        "params_schema": {},
        "depends_on": [],
        "publisher_url": "https://www.census.gov/foreign-trade/schedules/b/",
    },
    {
        "source": "CROSS",
        "label": "US CBP CROSS Rulings",
        "kind": "labels",
        "auto_download": True,
        "files": [],
        "params_schema": {
            "max_rulings": {"type": "int", "default": 5000, "required": False},
            "rps": {"type": "float", "default": 1.0, "required": False},
        },
        "depends_on": [],
        "publisher_url": "https://rulings.cbp.gov/",
    },
    {
        "source": "WCO",
        "label": "WCO International HS Nomenclature",
        "kind": "taxonomy",
        "auto_download": False,
        "files": [
            {
                "key": "file",
                "label": "WCO HS XLSX",
                "path": "data/taxonomy/wco_hs_2022.xlsx",
                "accept": ".xlsx,.xls",
            }
        ],
        "params_schema": {},
        "depends_on": [],
        "publisher_url": "https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition.aspx",
    },
    {
        "source": "HsEntityIndex",
        "label": "GLiNER entity index over HS codes",
        "kind": "derived",
        "auto_download": False,
        "files": [],
        "params_schema": {"level": {"type": "int", "default": None, "required": False}},
        "depends_on": ["HTS"],
        "publisher_url": None,
    },
    {
        "source": "GoldAssembly",
        "label": "Assemble eval gold splits from imported rows",
        "kind": "derived",
        "auto_download": False,
        "files": [],
        "params_schema": {
            "target": {"type": "int", "default": 1200, "required": False},
            "per_chapter": {"type": "int", "default": 30, "required": False},
        },
        "depends_on": ["CROSS"],
        "publisher_url": None,
    },
    {
        "source": "EU_DUAL_USE",
        "label": "EU Dual-Use Annex I (Reg 2021/821)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "Annex I XLSX", "path": "data/sanctions/eu_dual_use_annex_i.xlsx", "accept": ".xlsx,.xls"},
            {"key": "crosswalk", "label": "CN crosswalk (optional)", "path": "data/sanctions/cn_crosswalk.xlsx", "accept": ".xlsx,.xls", "optional": True},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02021R0821",
    },
    {
        "source": "EU_RUSSIA",
        "label": "EU Russia sanctions annexes (Reg 833/2014)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "Annex XLSX", "path": "data/sanctions/eu_russia_annex.xlsx", "accept": ".xlsx,.xls,.csv"},
        ],
        "params_schema": {
            "direction": {"type": "str", "default": "export", "required": True, "enum": ["export", "import", "both"]},
            "annex": {"type": "str", "default": "XVII", "required": False},
        },
        "depends_on": ["HTS"],
        "publisher_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833",
    },
    {
        "source": "BIS_CCL",
        "label": "US BIS Commerce Control List",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "ccl_file", "label": "CCL CSV/XLSX", "path": "data/sanctions/bis_ccl.csv", "accept": ".csv,.xlsx,.xls"},
            {"key": "crosswalk_file", "label": "HS-ECCN crosswalk XLSX", "path": "data/sanctions/bis_hs_eccn_crosswalk.xlsx", "accept": ".xlsx,.xls,.csv"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.bis.doc.gov/index.php/regulations/commerce-control-list-ccl",
    },
    {
        "source": "OFAC_SDN",
        "label": "US Treasury OFAC Specially Designated Nationals (SDN)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "sdn", "label": "sdn.csv", "path": "data/sanctions/ofac/sdn.csv", "accept": ".csv"},
            {"key": "add", "label": "add.csv (addresses)", "path": "data/sanctions/ofac/add.csv", "accept": ".csv", "optional": True},
            {"key": "alt", "label": "alt.csv (aliases)", "path": "data/sanctions/ofac/alt.csv", "accept": ".csv", "optional": True},
        ],
        "params_schema": {},
        "depends_on": [],
        "publisher_url": "https://sanctionslist.ofac.treas.gov/Home/SdnList",
    },
    {
        "source": "ITAR_USML",
        "label": "US Munitions List (ITAR, 22 CFR § 121)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "USML CSV/XLSX", "path": "data/sanctions/itar/usml.csv", "accept": ".csv,.xlsx,.xls"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M/part-121",
    },
    {
        "source": "IRAN",
        "label": "US sanctions on Iran (31 CFR Part 560)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "iran.yaml", "path": "data/sanctions/country_program/iran.yaml", "accept": ".yaml,.yml"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-560",
    },
    {
        "source": "DPRK",
        "label": "US sanctions on North Korea (31 CFR Part 510)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "dprk.yaml", "path": "data/sanctions/country_program/dprk.yaml", "accept": ".yaml,.yml"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-510",
    },
    {
        "source": "SYRIA",
        "label": "US sanctions on Syria (31 CFR Part 542)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "syria.yaml", "path": "data/sanctions/country_program/syria.yaml", "accept": ".yaml,.yml"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-542",
    },
    {
        "source": "CUBA",
        "label": "US sanctions on Cuba (31 CFR Part 515)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "cuba.yaml", "path": "data/sanctions/country_program/cuba.yaml", "accept": ".yaml,.yml"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-515",
    },
    {
        "source": "VENEZUELA",
        "label": "US sanctions on Venezuela (31 CFR Parts 591 & 592)",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "venezuela.yaml", "path": "data/sanctions/country_program/venezuela.yaml", "accept": ".yaml,.yml"},
        ],
        "params_schema": {},
        "depends_on": ["HTS"],
        "publisher_url": "https://www.ecfr.gov/current/title-31/subtitle-B/chapter-V/part-591",
    },
    {
        "source": "UN_CONSOLIDATED",
        "label": "UN Consolidated Sanctions List",
        "kind": "sanctions",
        "auto_download": True,
        "files": [],
        "params_schema": {},
        "depends_on": [],
        "publisher_url": "https://main.un.org/securitycouncil/en/sanctions/un-sc-consolidated-list",
    },
    {
        "source": "EU_CONSOLIDATED",
        "label": "EU Consolidated Financial Sanctions",
        "kind": "sanctions",
        "auto_download": False,
        "files": [
            {"key": "file", "label": "FSF XML", "path": "data/sanctions/eu_consolidated.xml", "accept": ".xml"},
        ],
        "params_schema": {},
        "depends_on": [],
        "publisher_url": "https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/",
    },
]

SOURCES_BY_NAME = {s["source"]: s for s in SOURCES}


class RunIn(BaseModel):
    params: dict[str, Any] | None = None


class ResetIn(BaseModel):
    include_rules: bool = False
    include_results: bool = True


@router.get("/refdata/sources")
async def list_sources(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    hs_total = (await db.execute(select(func.count()).select_from(HsCode))).scalar_one()
    train_by_source_rows = (
        await db.execute(
            select(HsTrainingExample.source, func.count()).group_by(HsTrainingExample.source)
        )
    ).all()
    train_by_source = {s: int(n) for s, n in train_by_source_rows}
    sanc_by_source_rows = (
        await db.execute(
            select(SanctionedCommodity.source, func.count()).group_by(SanctionedCommodity.source)
        )
    ).all()
    sanc_by_source = {s: int(n) for s, n in sanc_by_source_rows}

    out: list[dict[str, Any]] = []
    for s in SOURCES:
        last_run = (
            await db.execute(
                select(RefdataRun)
                .where(RefdataRun.source == s["source"])
                .order_by(RefdataRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if s["kind"] == "taxonomy":
            row_count = hs_total
        elif s["kind"] == "labels":
            mapping = {"ScheduleB": "schedule_b", "CROSS": "cross_ruling"}
            row_count = train_by_source.get(mapping.get(s["source"], s["source"].lower()), 0)
        elif s["kind"] == "sanctions":
            row_count = sanc_by_source.get(s["source"], 0)
        else:
            row_count = last_run.rows_upserted if last_run else 0

        # Check whether required upload files are present on disk.
        files_status = []
        for f in s["files"]:
            p = Path(f["path"])
            files_status.append(
                {
                    "key": f["key"],
                    "label": f["label"],
                    "path": f["path"],
                    "accept": f.get("accept"),
                    "optional": f.get("optional", False),
                    "present": p.exists(),
                    "size_bytes": p.stat().st_size if p.exists() else None,
                }
            )

        required_present = all(fs["present"] for fs in files_status if not fs["optional"])
        out.append(
            {
                **{k: v for k, v in s.items() if k != "files"},
                "files": files_status,
                "row_count": int(row_count),
                "ready_to_run": s["auto_download"] or required_present,
                "last_run": (
                    {
                        "id": last_run.id,
                        "started_at": last_run.started_at.isoformat() if last_run.started_at else None,
                        "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
                        "rows_upserted": last_run.rows_upserted,
                        "status": last_run.status,
                        "error_message": last_run.error_message,
                    }
                    if last_run
                    else None
                ),
            }
        )
    return {"sources": out}


@router.post("/refdata/{source}/upload")
async def upload_file(source: str, file: UploadFile, key: str) -> dict[str, Any]:
    src = SOURCES_BY_NAME.get(source)
    if not src:
        raise HTTPException(404, "unknown source")
    file_def = next((f for f in src["files"] if f["key"] == key), None)
    if not file_def:
        raise HTTPException(400, f"source {source} has no file slot '{key}'")
    dest = Path(file_def["path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"source": source, "key": key, "path": str(dest), "size_bytes": dest.stat().st_size}


@router.post("/refdata/{source}/run")
async def run_source(source: str, body: RunIn | None = None) -> dict[str, Any]:
    if source not in SOURCES_BY_NAME:
        raise HTTPException(404, "unknown source")
    params = (body.params if body else None) or {}
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        job = await pool.enqueue_job("run_refdata", source, params)
    finally:
        await pool.close()
    return {"source": source, "enqueued_job_id": job.job_id if job else None, "params": params}


@router.post("/refdata/run-all")
async def run_all(db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    """Enqueue every source that's ready to run, respecting depends_on ordering.

    Ordering is enforced lazily — the worker will run them serially in the order
    enqueued. Sources missing required files are skipped.
    """
    listing = (await list_sources(db))["sources"]
    by_name = {s["source"]: s for s in listing}
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    enqueued: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        for s in listing:
            if not s["ready_to_run"]:
                skipped.append({"source": s["source"], "reason": "missing files"})
                continue
            # Skip if dependencies have never run successfully.
            deps_ok = True
            for dep in s.get("depends_on", []):
                dep_rec = by_name.get(dep)
                if not dep_rec or (dep_rec.get("row_count") or 0) <= 0:
                    deps_ok = False
                    skipped.append({"source": s["source"], "reason": f"dep {dep} not loaded"})
                    break
            if not deps_ok:
                continue
            job = await pool.enqueue_job("run_refdata", s["source"], {})
            enqueued.append({"source": s["source"], "job_id": job.job_id if job else None})
    finally:
        await pool.close()
    return {"enqueued": enqueued, "skipped": skipped}


# Order matters for FK CASCADE; we use TRUNCATE ... CASCADE so concrete order is
# tolerant, but listing children first is still good practice.
DATA_TABLES = [
    "feedback_event",
    "screening_result",
    "shipment",
    "batch_job",
    "job_log",
    "eval_job",
    "training_run",
    "eval_run",
    "sanctioned_commodity_alias",
    "country_rule",
    "sanctioned_commodity",
    "hs_entity_index",
    "hs_training_example",
    "hs_code",
    "refdata_run",
]


@router.post("/refdata/reset")
async def reset_data(body: ResetIn, db: Annotated[AsyncSession, Depends(db_session)]) -> dict[str, Any]:
    """Drop ingested data; leave source files on disk and (by default) leave
    operator-authored rules alone."""
    truncated: list[str] = []
    tables = list(DATA_TABLES)
    if body.include_rules:
        tables.insert(0, "screening_rule")
    if not body.include_results:
        for t in ("feedback_event", "screening_result", "shipment", "batch_job"):
            if t in tables:
                tables.remove(t)
    # Use a single statement so CASCADE clears FKs in one go.
    await db.execute(text("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    await db.commit()
    truncated = tables
    return {"truncated": truncated, "files_kept": True}


@router.get("/refdata/files")
async def list_files() -> dict[str, Any]:
    """Inventory of all source files present on disk (for transparency)."""
    items: list[dict[str, Any]] = []
    for s in SOURCES:
        for f in s["files"]:
            p = Path(f["path"])
            items.append(
                {
                    "source": s["source"],
                    "key": f["key"],
                    "path": f["path"],
                    "present": p.exists(),
                    "size_bytes": p.stat().st_size if p.exists() else None,
                }
            )
    return {"files": items}
