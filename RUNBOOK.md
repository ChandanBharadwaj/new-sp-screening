# Runbook — Commodity Screening Engine (all phases)

Operator-facing companion to `README.md`. Real imported data only — the repo ships no synthetic gold or sanctions data.

## 0. Prereqs

- Python 3.11
- Node 18+ (for the frontend)
- Docker + Compose

## 1. Bring up infra and the API

```bash
cp .env.example .env
docker compose up -d postgres redis
pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload
```

First startup downloads bge-small, bge-reranker-v2-m3, and GLiNER — expect 20-40s cold-start (~1 GB RAM steady state).

## 2. Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

Pages: Status (default landing) · Upload · Results (drill into a result for full reasoning trace + override controls) · HS Browser · Sanctions Browser · Rules · Dashboards.

## 3. Phase 0+1 — HS taxonomy + training data + gold set

```bash
# US HTS taxonomy (~5k codes at level 6) + chapter/section notes
python -m app.refdata.hts.ingest --year 2025

# US Census Schedule B (operator downloads CSV from census.gov first)
python -m app.refdata.schedule_b.ingest --file ./data/schedule_b/schedule_b.csv

# CROSS rulings — two-pass, 1 rps polite default. ~80 min for 5000 rulings.
python -m app.refdata.cross.scraper --max-rulings 5000
python -m app.refdata.cross.ingest --html-dir data/cross_raw/rulings

# Populate hs_entity_index by running GLiNER over every HS code's title+description
python -m app.refdata.hs_entities.build

# Assemble the gold set from already-ingested rows, stratified by chapter
python -m app.refdata.gold.assemble --target 1200 --per-chapter 30
```

Every run writes a `refdata_run` row → visible on the Status page.

## 4. Train the LightGBM LTR fusion model

```bash
python -m app.training.ltr_dataset --gold eval/gold/splits/train.jsonl --out artifacts/ltr_train.csv
python -m app.training.ltr_train --in artifacts/ltr_train.csv --out artifacts/ltr.txt
```

Until `artifacts/ltr.txt` exists, the pipeline uses a deterministic linear-blend fallback (Status page shows "fallback" for the LTR card).

## 5. Phase 2 — Sanctions ingestion (real authoritative sources only)

Each source needs operator-downloaded files. See `docs/sanctions-sources.md` for provenance URLs and the list of sources that are skipped under the no-generated-data rule.

```bash
# EU Dual-Use Annex I (download XLSX from EUR-Lex; CN crosswalk optional)
python -m app.refdata.sanctions.eu_dual_use.ingest \
  --file ./data/sanctions/eu_dual_use_annex_i.xlsx \
  --crosswalk ./data/sanctions/cn_crosswalk.xlsx

# EU Russia sanctions (per-annex)
python -m app.refdata.sanctions.eu_russia.ingest \
  --file ./data/sanctions/eu_russia_annex_xvii.xlsx \
  --direction export --annex XVII

# US BIS Commerce Control List (needs published CCL + HS-ECCN crosswalk)
python -m app.refdata.sanctions.bis_ccl.ingest \
  --ccl-file ./data/sanctions/bis_ccl.csv \
  --crosswalk-file ./data/sanctions/bis_hs_eccn_crosswalk.xlsx

# UN Consolidated List (auto-downloads XML)
python -m app.refdata.sanctions.un.ingest --download

# EU Consolidated Sanctions (operator obtains the XML token first)
python -m app.refdata.sanctions.eu_consolidated.ingest --file ./data/sanctions/eu_consolidated.xml
```

## 6. Phase 2 — Sanctions eval

```bash
python -m eval.runners.build_sanctions_eval --positives 200 --negatives 200
python -m eval.runners.run_sanctions_eval --threshold 0.5
```

## 7. Phase 3 — Rules

Rules are operator-authored via the Rule Manager UI (`/rules`). No data import. Once analysts have labeled which shipments their rules SHOULD have hit (`eval/gold/rule_eval.jsonl`), run:

```bash
python -m eval.runners.run_rule_eval
```

## 8. Phase 4 — Feedback + Dashboards

- Mark HS corrections, dismiss sanctions or rule hits, add notes from the result detail page.
- View aggregate charts at `/dashboards`.
- Promote analyst corrections into gold candidates for review:

```bash
python -m eval.runners.sample_feedback_to_gold --since 2026-01-01
```

## 9. Phase 1 ship-gate eval

```bash
python -m eval.runners.run_eval --classifier pipeline --split test --report eval/reports/phase1.json
python -m eval.ci.compare --report eval/reports/phase1.json
```

## 10. Screen a single shipment

```bash
curl -s http://localhost:8000/api/v1/screen \
  -H "Content-Type: application/json" \
  -d '{"commodity_text":"women cotton trousers","cargo_text":"hemmed at ankle","origin_iso":"IN","destination_iso":"US"}' | jq
```

Returns the §10-shaped response (no allow/block/review — quantitative only).

## 11. Batch upload

```bash
docker compose up -d worker          # arq worker
curl -F "file=@shipments.csv" http://localhost:8000/api/v1/batch/upload
```

CSV required column: `commodity_text`. Optional: `cargo_text`, `origin_iso`, `destination_iso`, `external_ref`. Progress shows on Status and on the Upload page.

---

## Source provenance (Phase 2)

See `docs/sanctions-sources.md` for the complete list of authoritative URLs and the sources that are intentionally skipped under the no-generated-data rule.
