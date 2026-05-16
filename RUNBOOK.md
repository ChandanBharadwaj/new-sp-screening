# Runbook — Commodity Screening Engine (Phase 0 + Phase 1 scaffold)

This is the operator-facing companion to `README.md`. It tells you how to bring the
Python-only stack up locally and how to fill it with data.

The original `README.md` is the canonical spec; everything here implements it with
the Python-only stack the user chose (Java/Spring Boot orchestrator collapsed into
one FastAPI service; no schedulers; Status UI surfaces what's been done).

---

## 0. Prereqs

- Python 3.11
- Node 18+ (for the frontend)
- Docker + Compose (for local Postgres-with-pgvector and Redis)

## 1. Bring up infra and the API

```bash
cp .env.example .env
docker compose up -d postgres redis
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload
```

First startup downloads the bge-small embedder, the bge-reranker cross-encoder, and
GLiNER — expect 20-40 seconds of cold-start (and ~1 GB RAM steady state).

Visit `http://localhost:8000/docs` for OpenAPI, `http://localhost:8000/health` for
liveness.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173 — Vite proxies /api to :8000
```

The **Status** page is the landing screen. It will show:
- Postgres/Redis reachable
- Each model's load state + last-call latency
- Each refdata source's last-run timestamp + row count (will be empty until you run the ingesters)
- Latest eval run vs Phase 1 thresholds
- Recent CSV batch jobs

## 3. Load reference data (CLI only — no scheduler)

```bash
# US HTS taxonomy (~5k codes at level 6). Downloads htsdata.json to data/hts/.
python -m app.refdata.hts.ingest --year 2025

# US Census Schedule B (you need the CSV from census.gov)
python -m app.refdata.schedule_b.ingest --file ./data/schedule_b/schedule_b.csv

# CROSS rulings — starts from the curated stub at eval/gold/cross_curated.jsonl.
# To enrich with real rulings: scrape first, then ingest with --html-dir.
python -m app.refdata.cross.scraper --pages 20
python -m app.refdata.cross.ingest --html-dir data/cross_raw
```

Every run writes a `refdata_run` row → visible on the Status page.

## 4. Train the LightGBM LTR fusion model

```bash
python -m app.training.ltr_dataset --gold eval/gold/splits/train.jsonl --out artifacts/ltr_train.csv
python -m app.training.ltr_train --in artifacts/ltr_train.csv --out artifacts/ltr.txt
```

Until `artifacts/ltr.txt` exists, the pipeline runs with a deterministic linear blend
fallback (Status page shows "fallback" for the LTR model). The pipeline still
returns ranked candidates either way.

## 5. Run the eval harness

```bash
mkdir -p eval/reports
python -m eval.runners.run_eval --classifier baseline_noop --split test --report eval/reports/baseline.json
python -m eval.runners.run_eval --classifier pipeline      --split test --report eval/reports/pipeline.json
python -m eval.ci.compare --report eval/reports/pipeline.json
```

Every run writes an `eval_run` row → visible on the Status page with pass/fail
badges against `eval/ci/thresholds.yaml`.

## 6. Screen a single shipment

```bash
curl -s http://localhost:8000/api/v1/screen \
  -H "Content-Type: application/json" \
  -d '{"commodity_text":"women cotton trousers","cargo_text":"hemmed at ankle, zip closure","origin_iso":"IN","destination_iso":"US"}' | jq
```

Returns the §10-shaped response (no allow/block/review — quantitative only).

## 7. Batch upload

```bash
docker compose up -d worker          # spins up the arq worker
curl -F "file=@shipments.csv" http://localhost:8000/api/v1/batch/upload
```

CSV minimum: `commodity_text` column. Optional: `cargo_text`, `origin_iso`,
`destination_iso`, `external_ref`. Progress shows on Status and on the Upload page.

---

## What's a stub vs. what's real

- **Real**: schema, migrations, ML model wrappers, pipeline orchestration, retrieval SQL, fusion, confidence metrics, API + worker + Status UI, HTS ingester, Schedule B parser, CROSS scraper + HTML parser, LightGBM trainer, eval runners, CI workflow.
- **Stub**: the gold-dataset splits (`eval/gold/splits/*.jsonl`) and the curated CROSS file each carry only ~5-10 rows so the harness boots end-to-end. Expand these to ≥1000 pairs to actually clear the Phase 1 ship gate.

The Phase 1 accuracy gate (top-1 subheading ≥85%, etc.) cannot be hit until both the
training data and the gold set are real-sized. Everything needed to fill them is
wired; only the data itself is left.
