# Runbook — Commodity Screening Engine

Operator runbook. Everything is driven from the web UI; there are no commands to memorize.

## Bring up the system (one-time, infra)

```bash
docker compose up -d
```

This starts Postgres (with pgvector), Redis, the FastAPI app, and the arq worker.
The first time the app starts it downloads the sentence-transformer + cross-encoder + GLiNER weights (~1 GB total) — give it 30–60 seconds before opening the UI.

Frontend (in `frontend/`):

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

## Operator workflow — everything happens in the UI

### 1. Status page (landing)

Open the app. The **Status** page is the default landing screen.

- Top row: green/red dots for Postgres and Redis, engine version, uptime.
- Models card: which models are loaded, load time, last call latency.
- Reference data: every source with last-run timestamp, row count, and an inline **Run** button.
- Eval: latest accuracy + p95 vs ship thresholds.
- Recent batches.

### 2. Admin page — load every data source

Click **Admin** in the navbar. You'll see every refdata source grouped by kind (HS taxonomy / labeled training data / derived / sanctions).

For each source:
- A **publisher** link to the authoritative URL.
- For sources that need files (Schedule B, EU Dual-Use Annex I, EU Russia annexes, BIS CCL, EU Consolidated FSF): **Upload** buttons. Pick the file you downloaded from the publisher; it persists to `./data/<source>/`.
- For auto-download sources (HTS, CROSS, UN Consolidated): no file upload needed.
- Params form: tweak per-source knobs (HTS year, CROSS max_rulings, EU Russia annex/direction).
- A **Run** button. Disabled until any required files are uploaded.

While a source is running, its card shows a live progress bar driven by `rows_upserted` in the database. You can leave the page and come back — the Status row stays in sync.

Two top-level buttons:
- **Run all ready sources** — kicks off every source whose required files are present, respecting `depends_on` (HTS before HsEntityIndex, CROSS before GoldAssembly).
- **Reset data…** — opens a confirm panel with checkboxes:
  - by default truncates every ingested data table (`hs_code`, `hs_training_example`, `sanctioned_commodity`, `country_rule`, `hs_entity_index`, `refdata_run`, plus `shipment` / `screening_result` if `include_results` is checked).
  - leaves all source files on disk under `./data/`, so you can re-run any source one click later without re-downloading.
  - by default leaves operator-authored `screening_rule` rows alone (toggle `include_rules` to also drop them).

### 3. Data page — browse what you have

Click **Data** in the navbar. Five tabs:
- **Training examples** — the `hs_training_example` table with source filter, full-text search, chapter filter, pagination.
- **Shipments** — every shipment you've screened.
- **Eval runs** — accuracy + latency history.
- **Refdata runs** — every ingestion run with status + row counts (live-updates).
- **Files on disk** — every file under `./data/`.

### 4. Browse / manage the rest

- **HS** — chapter tree + search over the HS taxonomy.
- **Sanctions** — country-pair heatmap + sanctioned-commodity drill-down with provenance links.
- **Rules** — author semantic rules, test them live against sample text before saving, view version history.
- **Upload** — drop a CSV of shipments for batch screening.
- **Results** — table of screening results; click a row to see the full §10 reasoning trace and submit overrides (HS correction, dismiss sanction/rule hit, free-text note) that flow into `feedback_event`.
- **Dashboards** — chapter volume, sanction sources, country-pair heatmap, score histograms, override-rate trend.

## Source provenance

Every authoritative URL the operator needs to download files from is listed in `docs/sanctions-sources.md` (sanctions) and is also surfaced as a "publisher" link on each source card in the Admin page.

## What's where on disk

```
data/
  hts/                       # cached USITC HTS JSON (auto-downloaded)
  cross_raw/
    search/                  # cached search pages
    rulings/                 # cached individual ruling HTML
  schedule_b/                # operator-uploaded Census CSV
  sanctions/                 # operator-uploaded EU/BIS/UN XLSX/XML files
artifacts/
  ltr.txt                    # LightGBM model — appears once training has run
eval/
  gold/splits/{train,dev,test}.jsonl   # produced by Admin → GoldAssembly
  reports/                   # eval run reports
```

## If something goes wrong

- A run's status card on the Admin page shows the error message inline.
- The Refdata-runs tab on the Data page shows every run's history.
- Hit **Run** again to retry — uploads/cached files are reused.
