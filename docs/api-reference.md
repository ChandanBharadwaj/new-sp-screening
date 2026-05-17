# API reference

Every HTTP endpoint exposed by the FastAPI app, grouped by router file.
Routers are mounted in `app/main.py:56-70`. All routes share the
`/api/v1` prefix.

## Conventions

- **Auth.** There is no auth in v1 — every endpoint is reachable on the
  network the app binds to. The CORS allowlist (`app/main.py:48-53`)
  permits the local frontend at `localhost:5173` and `localhost:3000`.
- **Database session.** Most handlers inject `db: AsyncSession` via the
  `db_session` dependency (`app/api/deps.py`).
- **Model registry.** Endpoints that touch the embedder or reranker
  (e.g., `/screen`, `/rules`) inject `reg: ModelRegistry` via the
  `models` dependency.
- **Errors.** Handlers raise `HTTPException` for 404 / 400 cases. The
  body is a standard FastAPI `{"detail": "..."}`.
- **Job enqueueing.** Long-running operations (refdata ingest, LTR
  training, eval, batch screening) return `{"enqueued_job_id": ..., ...}`
  immediately and run on the arq worker. Tail progress via
  `/api/v1/jobs/{run_table}/{run_id}/stream` (see below).
- **Streaming.** `/api/v1/jobs/.../stream` is SSE. `/api/v1/batch/{id}/errors.csv`
  is a `StreamingResponse` with `Content-Type: text/csv`.

## Top-level

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok", "engine_version": str}` (`app/main.py:73`) |

## Screening — `app/api/routes_screen.py`

The two screening endpoints share `ShipmentIn`
(`app/schemas/screen.py:7-15`) as their request body:

```json
{
  "external_ref":     "optional client-side id",
  "commodity_text":   "required",
  "cargo_text":       "optional",
  "origin_iso":       "JP",
  "destination_iso":  "RU",
  "shipment_value":   480000,
  "currency":         "USD",
  "metadata":         {"incoterm": "FOB"}
}
```

| Method | Path | Persists? | Response | Defined at |
|---|---|---|---|---|
| POST | `/api/v1/screen` | yes (Shipment + ScreeningResult) | full `ScreeningResultOut` (`app/schemas/screen.py:49-58`) | `routes_screen.py:48` |
| POST | `/api/v1/classify` | no | `hs_classification` block only | `routes_screen.py:71` |

End-to-end semantics for `/screen` are documented in
[`inference.md`](inference.md) and [`data-flow-example.md`](data-flow-example.md).

## Results — `app/api/routes_results.py`

| Method | Path | Defined at |
|---|---|---|
| GET | `/api/v1/results` | `routes_results.py:124` |
| GET | `/api/v1/results/{result_id}` | `routes_results.py:227` |

`GET /results` supports rich filtering:

| Query param | Type | Default | Effect |
|---|---|---|---|
| `limit` | int (≤500) | 50 | page size |
| `offset` | int (≤100000) | 0 | pagination |
| `chapter` | str | — | filter by top-1 HS chapter (2-digit) |
| `min_score` | float | — | filter by top-1 score |
| `origin_iso` / `destination_iso` | str | — | route filter |
| `abstained` | bool | — | abstention surface filter |
| `has_sanctions` / `has_rules` | bool | — | flag filters |
| `since` | datetime | — | created_at lower bound |
| `sort` | `recent` \| `risk_desc` \| `confidence_asc` | `recent` | order |

The `risk_desc` order uses an SQL expression built at
`routes_results.py:17-29`:

```
max_sanction_similarity + 0.5 * max_rule_delta + 0.3 * (abstained ? 1 : 0)
```

Each row in the response carries `result_id`, `shipment_id`,
`external_ref`, `commodity_text`, route fields, the top-1 HS code +
chapter + score, abstention flags, counts of sanctions/rules, the
max similarity/delta, `engine_version`, and `created_at`.

`GET /results/{result_id}` returns the full payload as persisted —
`hs_classification`, `sanction_matches` (list), `rule_matches` (list),
`extracted_entities`, `confidence_metrics`, `latency_ms`, plus the
nested `shipment` block (`commodity_text`, `cargo_text`, route).

## HS taxonomy — `app/api/routes_hs.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/hs/search?q=&limit=` | full-text search HS codes | `routes_hs.py:27` |
| GET | `/api/v1/hs/tree` | top-level chapters (level=2) | `routes_hs.py:43` |
| GET | `/api/v1/hs/{code}` | HS code with children | `routes_hs.py:51` |

All return `{"items": [...]}` where each item is the HS row
(`code`, `level`, `chapter`, `parent_code`, `title`, `description`,
`chapter_notes`, `section_notes`).

## Sanctions browser — `app/api/routes_sanctions.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/sanctions/sources` | source → row-count list | `routes_sanctions.py:14` |
| GET | `/api/v1/sanctions/by-country-pair?origin=&destination=&limit=` | active rules for a route | `routes_sanctions.py:26` |
| GET | `/api/v1/sanctions/heatmap` | (origin, destination, count) cells | `routes_sanctions.py:70` |
| GET | `/api/v1/sanctions/{sanction_id}` | sanction detail with country_rules | `routes_sanctions.py:94` |

`by-country-pair` accepts NULLs on either side (`origin=*` or
`destination=*` matches "any"). The heatmap renders the global
`country_rule` table.

## Rules — `app/api/routes_rules.py`

`ScreeningRule` rows are user-authored, versioned in-place (update
deactivates the previous row and inserts a new one with `version+1`).

Schemas in `app/schemas/rule.py`: `RuleIn` (input), `RuleOut`
(response), `RuleTestIn` / `RuleTestOut` (dry-run test).

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/rules?active_only=` | list rules | `routes_rules.py:51` |
| POST | `/api/v1/rules` | create rule (embeds phrase) | `routes_rules.py:63` |
| GET | `/api/v1/rules/{rule_id}` | detail + version history | `routes_rules.py:89` |
| PUT | `/api/v1/rules/{rule_id}` | new version of an existing rule | `routes_rules.py:107` |
| DELETE | `/api/v1/rules/{rule_id}` | soft-delete (`active=false`) | `routes_rules.py:141` |
| POST | `/api/v1/rules/{rule_id}/test` | run rule against sample cargo | `routes_rules.py:155` |
| POST | `/api/v1/rules/test-phrase` | score a phrase without saving | `routes_rules.py:193` |

`RuleIn` carries `name`, `phrase` (always required as the embedding
seed), optional `phrase_group = {"mode": "any_of"|"all_of", "phrases": [...]}`,
`threshold ∈ [0, 1]`, optional JSON `conditions` (DSL: `min_value`,
`max_value`, `currency_in`, `metadata_eq`), `origin_iso`,
`destination_iso`, `active`, `created_by`.

## Thresholds — `app/api/routes_thresholds.py`

Editable ship-gate thresholds backed by the `threshold` table; seeded
from `eval/ci/thresholds.yaml` on first access
(`routes_thresholds.py:33-40`). The YAML stays the canonical CI gate;
the DB copy drives the Status page and operator edits.

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/thresholds` | list current thresholds + YAML seed | `routes_thresholds.py:55` |
| PUT | `/api/v1/thresholds` | upsert single threshold (`source="ui"`) | `routes_thresholds.py:73` |
| POST | `/api/v1/thresholds/reset` | overwrite all with YAML seed | `routes_thresholds.py:89` |

## Training — `app/api/routes_training.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| POST | `/api/v1/training/ltr/run` | enqueue `train_ltr` arq job | `routes_training.py:41` |
| GET | `/api/v1/training/runs` | last 20 `TrainingRun` rows | `routes_training.py:57` |
| GET | `/api/v1/training/runs/{run_id}` | single training run | `routes_training.py:65` |

Body for `POST /ltr/run` (all optional):

```json
{
  "gold":        "eval/gold/splits/train.jsonl",
  "dataset_csv": "artifacts/ltr_train.csv",
  "artifact":    "artifacts/ltr.txt",
  "limit":       null
}
```

Response: `{"enqueued_job_id": "...", "params": {...}}`. Tail logs via
`/api/v1/jobs/training_run/{run_id}/stream`. See [`training.md`](training.md).

## Evaluation — `app/api/routes_eval.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| POST | `/api/v1/eval/run` | enqueue `run_eval_job` arq job | `routes_eval.py:39` |
| GET | `/api/v1/eval/jobs` | last 20 `EvalJob` rows | `routes_eval.py:54` |
| GET | `/api/v1/eval/jobs/{job_id}` | single eval job | `routes_eval.py:62` |

Body for `POST /run`:

```json
{
  "classifier": "pipeline",   // or "baseline_noop"
  "split":      "test",       // train | dev | test
  "limit":      null
}
```

Tail logs via `/api/v1/jobs/eval_job/{job_id}/stream`. See [`evaluation.md`](evaluation.md).

## Admin — `app/api/routes_admin.py`

The Admin UI lives on top of these endpoints. The source catalog
(`SOURCES` constant, `routes_admin.py:40+`) is the canonical list of
ingestible refdata sources; every entry carries `auto_download` /
required file uploads / params / `depends_on` ordering.

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/admin/refdata/sources` | source catalog + row counts + last run | `routes_admin.py:284` |
| POST | `/api/v1/admin/refdata/{source}/upload?key=...` | upload a required source file (multipart) | `routes_admin.py:361` |
| POST | `/api/v1/admin/refdata/{source}/run` | enqueue `run_refdata` for one source | `routes_admin.py:376` |
| POST | `/api/v1/admin/refdata/run-all` | enqueue all ready sources in dep order | `routes_admin.py:389` |
| POST | `/api/v1/admin/refdata/reset` | truncate ingested tables | `routes_admin.py:444` |
| GET | `/api/v1/admin/refdata/files` | inventory of expected files on disk | `routes_admin.py:463` |

`POST /reset` body:

```json
{"include_rules": false, "include_results": true}
```

`include_rules=true` also clears `screening_rule`; otherwise the
operator's rules survive a reset. Uploaded source files on disk are
never deleted by this endpoint.

## Batch screening — `app/api/routes_batch.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| POST | `/api/v1/batch/upload` | upload CSV; enqueue screening per row | `routes_batch.py:23` |
| GET | `/api/v1/batch/{batch_id}` | batch job status | `routes_batch.py:68` |
| GET | `/api/v1/batch/{batch_id}/errors` | paginated per-row errors | `routes_batch.py:85` |
| GET | `/api/v1/batch/{batch_id}/errors.csv` | CSV download of errors | `routes_batch.py:122` |

CSV upload requires column `commodity_text`. Optional columns:
`cargo_text`, `origin_iso`, `destination_iso`, `shipment_value`,
`currency`, `external_ref`. Response on success:

```json
{"batch_id": "uuid", "total_rows": 42, "status": "running"}
```

Each row enqueues a separate screening job; failures land in
`batch_job_error` with `row_index`, `raw_row` (the CSV row as dict),
and `error_message`. The CSV export streams the same data with a
`Content-Disposition: attachment` header.

## Feedback — `app/api/routes_feedback.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| POST | `/api/v1/feedback` | log a `FeedbackEvent` for a result | `routes_feedback.py:24` |
| GET | `/api/v1/feedback/{result_id}` | events for one result | `routes_feedback.py:45` |

Body for `POST /feedback`:

```json
{
  "result_id":    "<uuid of ScreeningResult>",
  "event_type":   "hs_corrected",  // hs_corrected | sanction_dismissed | rule_dismissed | escalated
  "before_value": {"hs_code": "854231"},
  "after_value":  {"hs_code": "381800"},
  "notes":        "Operator note",
  "analyst_id":   "user@example.com"
}
```

See [`feedback-loop.md`](feedback-loop.md) for what happens after the
event is logged.

## Data browser — `app/api/routes_data.py`

Browsing endpoints for the Data page. All return paginated lists with
`{items, total, limit, offset}` shapes unless noted.

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/data/training-examples` | `hs_training_example` rows + filter by source/chapter/text | `routes_data.py:23` |
| GET | `/api/v1/data/shipments` | recent shipments + full-text search | `routes_data.py:72` |
| GET | `/api/v1/data/eval-runs` | recent `EvalRun` rows | `routes_data.py:107` |
| GET | `/api/v1/data/refdata-runs?source=` | recent `RefdataRun` rows | `routes_data.py:135` |
| GET | `/api/v1/data/files` | walk `./data/`; list cached files + mtime | `routes_data.py:162` |

## Status — `app/api/routes_status.py`

Health and freshness endpoints powering the Status page.

| Method | Path | What it tells you | Defined at |
|---|---|---|---|
| GET | `/api/v1/status/system` | engine version, uptime, Postgres & Redis reachability | `routes_status.py:85` |
| GET | `/api/v1/status/models` | which models are loaded + load times + last call latency | `routes_status.py:112` |
| GET | `/api/v1/status/refdata` | per-HS-source last run + row counts + staleness (90/365-day gates) | `routes_status.py:117` |
| GET | `/api/v1/status/sanctions` | per-sanctions-source last run + row counts + staleness (7/30-day gates) | `routes_status.py:184` |
| GET | `/api/v1/status/rules` | total + active rule counts | `routes_status.py:247` |
| GET | `/api/v1/status/eval` | latest eval runs + thresholds + pass/fail per metric | `routes_status.py:258` |
| GET | `/api/v1/status/batches` | last 10 batch jobs | `routes_status.py:293` |

Staleness severity is one of `green` / `amber` / `red` / `gray`
("never run"). Sanctions sources have **stricter** thresholds than HS
taxonomy because regulators publish on a near-weekly cadence.

## Dashboards — `app/api/routes_dashboards.py`

Aggregates over `screening_result` + `feedback_event` for charts.

| Method | Path | Returns | Defined at |
|---|---|---|---|
| GET | `/api/v1/dashboards/chapter-volume` | `{items: [{chapter, count}]}` (top-1 HS chapter) | `routes_dashboards.py:13` |
| GET | `/api/v1/dashboards/sanction-hits-by-source` | `{items: [{source, count}]}` | `routes_dashboards.py:32` |
| GET | `/api/v1/dashboards/country-pair-heatmap` | `{cells: [{origin_iso, destination_iso, count}]}` | `routes_dashboards.py:51` |
| GET | `/api/v1/dashboards/score-histograms` | `{top1_score: [{bucket, count}]}` (10 buckets, 0-1) | `routes_dashboards.py:73` |
| GET | `/api/v1/dashboards/override-rate-trend` | `{items: [{chapter, corrections, total, rate}]}` (from feedback) | `routes_dashboards.py:101` |

The `override-rate-trend` endpoint is what closes the loop with
feedback — see [`feedback-loop.md`](feedback-loop.md).

## Job log streaming — `app/api/routes_jobs.py`

| Method | Path | Description | Defined at |
|---|---|---|---|
| GET | `/api/v1/jobs/{run_table}/{run_id}/stream` | SSE — pushes new `JobLog` lines as `log` events; terminates with `done` or `error` | `routes_jobs.py:114` |
| GET | `/api/v1/jobs/{run_table}/{run_id}/logs` | non-streaming fallback — full log array | `routes_jobs.py:129` |

`run_table` must be one of `refdata_run` / `training_run` / `eval_job`
(`RUN_MODELS` map at `routes_jobs.py:27-31`). Any other slug → 404.

SSE event shape:

```text
event: log
data: {"id": 123, "ts": "2026-05-17T16:30:00+00:00", "level": "info", "line": "..."}

event: done
data: {"status": "success"}
```

The stream uses 500ms polling against the `job_log` table; it
auto-closes within ~1s of the parent run leaving the `running` state.

## Calling from a script

```python
import httpx, json
async with httpx.AsyncClient(base_url="http://localhost:8000") as c:
    resp = await c.post("/api/v1/screen", json={
        "commodity_text": "silicon wafers 300mm",
        "origin_iso": "JP",
        "destination_iso": "RU",
        "shipment_value": 480000,
    })
    payload = resp.json()
    print(payload["hs_classification"]["top_candidates"][0])
```

For job-style endpoints, capture `enqueued_job_id`, poll the relevant
GET endpoint until `status != "running"`, and stream
`/api/v1/jobs/.../stream` in parallel if you want live logs.
