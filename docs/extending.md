# Extending the system

A cookbook of step-by-step recipes for the most common extensions.
Each section starts with "when to reach for this," lists every file
you have to touch, and ends with verification steps. Cross-references
into the existing docs point at the deeper material.

## Quick map: what needs to change for what

| Extension | Touches code | Touches schema | Touches model | Requires retrain |
|---|---|---|---|---|
| New sanctions/refdata source | yes | maybe (only if a new table) | no | no |
| New retrieval signal / LTR feature | yes | no | yes | **yes** |
| New pipeline stage | yes | no | no | only if it changes feature inputs |
| New rule field / condition | yes | maybe | no | no |
| New API endpoint | yes | no | no | no |
| New arq job | yes | maybe (new run table) | no | no |
| New eval metric | yes | maybe (column on `eval_run`) | no | no |

## 1. Add a new sanctions / refdata source

**When.** A regulator publishes a list the system doesn't ingest yet
(say, the Swiss SECO sanctioned-goods register).

**Background reading.** [`ingestion.md`](ingestion.md).

### Steps

1. **Add the publisher metadata** to
   `app/api/routes_admin.py:SOURCES` (`routes_admin.py:40+`). Decide
   `auto_download`, required uploaded files, params schema, and
   `depends_on` (list other source keys that must run first — almost
   always `["HTS"]` so `expand_hs_prefixes` resolves).

2. **Create the ingester** at
   `app/refdata/sanctions/<source_slug>/ingest.py`:

   ```python
   from pathlib import Path
   from app.refdata.common import with_run_logging
   from app.refdata.sanctions.common import (
       upsert_sanctioned_commodities, expand_rows_in_place,
   )

   async def main_async(path: Path) -> None:
       async with with_run_logging("SECO", notes=str(path)) as (db, run):
           rows = _parse(path)              # source-specific
           await expand_rows_in_place(db, rows)   # 2/4-digit → 6-digit
           result = await upsert_sanctioned_commodities(
               db, rows, source="SECO", run=run,
           )
           run.rows_upserted = result["sanctioned"]
   ```

   - Use `async def main_async(...)` as the entry point — it's the
     uniform contract every ingester satisfies (see
     [`naming-conventions.md`](naming-conventions.md)).
   - Put source-specific parsing in a sibling `parser.py` if it grows
     past ~50 lines.
   - **Always call `expand_hs_prefixes` / `expand_rows_in_place`** if
     the source publishes 2/4-digit codes. The structured-overlap
     join uses 6-digit codes, so unexpanded prefixes silently never
     match (see `app/refdata/sanctions/common.py:131-162`).

3. **Wire the dispatcher.** Add a branch to
   `app/workers/refdata_jobs.py:run_refdata` (`refdata_jobs.py:34-112`)
   that routes the `source` string to your `main_async`. Follow the
   existing pattern for handling optional `params`.

4. **Build canonical row dicts.** Each row passed to
   `upsert_sanctioned_commodities` must conform to:

   ```python
   {
       "source_record_id": "<external stable id>",   # idempotency
       "description":      "...",
       "hs_codes":         ["381800", ...],          # 6-digit, post-expand
       "restriction_type": "blocked",                # or prohibited / licensed
       "effective_from":   date(2024, 1, 1),         # nullable
       "effective_to":     None,
       "provenance_url":   "https://...",
       "country_rules": [
           {"origin_iso": None, "destination_iso": "RU",
            "restriction_type": "prohibited", "conditions": None}
       ],
   }
   ```

5. **Aliases (if applicable).** Sources with AKA / transliteration
   data should populate `sanctioned_commodity_alias` via
   `insert_aliases(...)` after the upsert
   (`app/refdata/sanctions/common.py:171`).

6. **Provenance doc.** Append a row to
   `docs/sanctions-sources.md` with publisher URL, file format, HS
   coverage, and a link to your new ingester.

### Verify

- `POST /api/v1/admin/refdata/SECO/run` and tail
  `/api/v1/jobs/refdata_run/{id}/stream`.
- `GET /api/v1/admin/refdata/sources` should now show the source with
  a `success` last run and a non-zero `row_count`.
- `GET /api/v1/sanctions/sources` reflects the new source's count.
- A screening on a relevant route surfaces a `sanction_matches` entry
  with `source: "SECO"`.

### Adding a *non*-sanctions refdata source

If you're adding something like a new HS taxonomy or a new
training-example feed (say, EU CN explanatory notes), the pattern is
the same except:

- The target table is `hs_code` or `hs_training_example`, not
  `sanctioned_commodity`.
- You write your own upsert with `ON CONFLICT DO NOTHING` against the
  table's unique constraint — there is no equivalent of
  `upsert_sanctioned_commodities` for those tables.
- `kind` in `SOURCES` becomes `"taxonomy"` or `"labels"` instead of
  `"sanctions"`.

## 2. Add a new retrieval signal / LTR feature

**When.** You have a hypothesis that a new signal (e.g.,
"how many `material` NER spans overlap the candidate's
`hs_entity_index`") will help the LTR rank better.

**Background reading.** [`inference.md`](inference.md) §"HS ranking",
[`training.md`](training.md) §"Feature contract — handle with care".

### Steps

1. **Compute the signal on the candidate dict.** Choose where it
   belongs:

   - A new retrieval branch → new module under
     `app/pipeline/retrieval/`, called from
     `orchestrator._hs_rank_for_text` (`app/pipeline/orchestrator.py:30`).
   - A new feature derived inside `fusion.fuse` → just add it to the
     per-candidate `feats` dict (`app/pipeline/fusion.py:40-52`).

2. **Declare the field in `union.NUMERIC_FIELDS`** if it's a new
   retrieval-branch numeric (`app/pipeline/retrieval/union.py:23`).
   The merge preserves any field in this list.

3. **Append it to `FEATURE_ORDER`** in `app/models/ltr.py:10-18`.
   **Append, do not insert in the middle** — the booster was trained
   on the previous order and silently mis-reads any reordering.

4. **Capture the new feature during dataset build.** Add a row in
   `app/training/ltr_dataset.py:96-110` so the new column lands in
   `artifacts/ltr_train.csv`.

5. **Retrain.** Run
   `POST /api/v1/training/ltr/run`; verify the resulting
   `TrainingRun.metrics.ndcg` improves vs the previous run on
   `/api/v1/data/eval-runs`.

6. **Coordinated deploy.** Ship the code change and the new
   `artifacts/ltr.txt` together. Mismatched feature order between
   booster and inference produces silently-bad scores, not an error.

### Verify

- `POST /api/v1/eval/run { "classifier": "pipeline", "split": "test" }`
  must clear `eval/ci/thresholds.yaml`.
- Inspect a single screening's `score_components` (return value of
  `POST /api/v1/classify`) — the new field should appear alongside
  `dense`, `sparse`, `entity_overlap`, `cross_encoder`, etc.

## 3. Add a new pipeline stage

**When.** A new stage is needed (e.g., "language detection" before
NER for non-English shipments).

**Background reading.** [`inference.md`](inference.md).

### Steps

1. **Decide pre or post-NER.** Pre-NER stages must run sequentially
   on the text. Post-NER stages can sometimes run in parallel via
   `asyncio.gather`.

2. **Create the module.** Add `app/pipeline/<stage>.py` exposing a
   pure function: input → output. Keep it stateless; model objects
   come in via the `models: ModelRegistry` argument from the
   orchestrator if needed.

3. **Call from the orchestrator** at
   `app/pipeline/orchestrator.py:run_screen`. Add a
   `timer.mark("<stage>")` so the latency surface
   (`latency_ms.<stage>`) becomes visible without further plumbing
   (`app/telemetry.py` defines `StageTimer`).

4. **Persist in the response if useful.** If downstream consumers
   need the output (the way they need `extracted_entities`), add it
   to `app/pipeline/assemble.py:build` and the relevant pydantic
   schema in `app/schemas/screen.py`.

5. **Avoid breaking persistence.** `ScreeningResult.hs_candidates`,
   `.sanction_matches`, `.rule_matches`, `.extracted_entities` are
   JSONB columns — extending their shape is safe. Introducing a new
   top-level field on `ScreeningResult` needs a Liquibase changeset
   under `db/changelog/changes/`.

### Verify

- A unit test under `tests/pipeline/test_<stage>.py` covering the
  empty input case and a typical input case.
- `POST /api/v1/screen` returns the new field; `latency_ms.<stage>`
  appears.
- An end-to-end test (`tests/api/test_*`) checks the new field on
  the persisted `ScreeningResult`.

## 4. Add a new rule condition

**When.** Operators ask for a condition the current DSL doesn't
support (e.g., `weight_kg_in: [0, 500]`).

**Background reading.** [`inference.md`](inference.md) §"Rules match".

### Steps

1. **Schema-side.** Decide if the condition is shipment-level (already
   in `shipment.metadata_json` or columns) or needs a new column on
   `shipment` (rare).

2. **Wire the DSL.** Extend `_eval_conditions` in
   `app/pipeline/rules.py:37-54`:

   ```python
   if "weight_kg_in" in cond:
       w = shipment.get("metadata", {}).get("weight_kg")
       lo, hi = cond["weight_kg_in"]
       if w is None or w < lo or w > hi:
           return False
   ```

3. **Document the new key.** Update the docstring on
   `app/pipeline/rules.py:12-19` (Conditions DSL) and the operator-
   facing copy on the Rule editor page in the frontend.

4. **No schema change is needed** for shipment fields you read out of
   `metadata`. Adding a real new column on `shipment` needs a
   Liquibase changeset and a `Shipment` model update.

### Verify

- `POST /api/v1/rules/test-phrase` with the new condition fires
  expected `conditions_satisfied` outcomes.
- Save the rule and run an end-to-end `POST /api/v1/screen` against
  a shipment that should and a shipment that should not match.

## 5. Add a new API endpoint

**When.** A new resource needs an HTTP surface.

**Background reading.** [`api-reference.md`](api-reference.md).

### Steps

1. **Decide the resource.** One router per resource is the
   convention (`routes_<resource>.py` in `app/api/`). Reuse an
   existing router if the new endpoint is a sub-resource of an
   existing one (e.g., `GET /api/v1/results/{id}/sanctions` belongs
   in `routes_results.py`).

2. **Define schemas.** Pydantic models for request and response in
   `app/schemas/<resource>.py`.

3. **Write the route.** Use the standard dependency-injection
   pattern (`Annotated[AsyncSession, Depends(db_session)]`,
   `Annotated[ModelRegistry, Depends(models)]` if needed).

4. **Mount the router** in `app/main.py:56-70`.

5. **Skip auth.** There is no auth layer to satisfy in v1 (see
   [`api-reference.md`](api-reference.md) §"Conventions"). If auth is
   added later it'll be a single middleware in `app/main.py`, not a
   per-route concern.

6. **Document.** Add a row to the relevant section of
   [`api-reference.md`](api-reference.md).

### Verify

- Unit test the handler under `tests/api/test_<resource>.py`. Reuse
  the test client fixture from `tests/conftest.py`.
- Try the call from the OpenAPI docs at `http://localhost:8000/docs`.

## 6. Add a new arq job

**When.** A new long-running operation needs to run off the request
path (e.g., "rebuild dense embeddings for `sanctioned_commodity`
overnight").

**Background reading.** [`ingestion.md`](ingestion.md),
[`training.md`](training.md).

### Steps

1. **Create the worker function.** Add
   `app/workers/<family>_jobs.py` with
   `async def <job_name>(ctx, params) -> dict`. The first argument
   `ctx` is the arq context (unused but mandatory); `params` is the
   dict you'll pass when enqueueing.

2. **Track lifecycle.** Add a `<job>_run` or reuse an existing run
   table (`RefdataRun`, `TrainingRun`, `EvalJob`) — pick one whose
   shape fits, or add a new model + Liquibase changeset. Open the
   row in `running`, finalize on success/failure.

3. **Stream logs.** Use `app.workers.log_helper.append_log(db,
   "<table>", run_id, msg)` so `/api/v1/jobs/<table>/{id}/stream`
   surfaces progress. Add the table to `RUN_MODELS` in
   `app/api/routes_jobs.py:27` if it's new.

4. **Register the function** in
   `app/workers/arq_app.py` so the worker picks it up.

5. **Add the enqueue endpoint.** Typical shape:

   ```python
   from arq.connections import RedisSettings, create_pool
   pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
   try:
       job = await pool.enqueue_job("<job_name>", params)
   finally:
       await pool.close()
   return {"enqueued_job_id": job.job_id if job else None}
   ```

### Verify

- Enqueue from the API; tail logs via SSE; confirm the run row
  transitions through `running` → `success`.
- A failure path emits `FAILED: <msg>` and leaves
  `status="failed"` + `error_message` on the run row.

## 7. Add a new eval metric

**When.** A new ranking or quality metric (e.g., normalized DCG at K)
should join `top1_subheading` et al.

**Background reading.** [`evaluation.md`](evaluation.md).

### Steps

1. **Implement the metric.** Add a function to
   `eval/metrics/ranking.py` (or a new module) operating on
   `(predictions: list[list[str]], gold: list[str])`.

2. **Compute it in the runner.** `eval/runners/run_eval.py:122-129`
   builds the `metrics` dict — add the new key here.

3. **Persist it.** Either:

   - Add a column to `EvalRun` (`app/db/models.py:223+`) via a
     Liquibase changeset and write it in `_persist_run`
     (`eval/runners/run_eval.py:51-77`), or
   - Leave it inside `EvalRun.report_json` and surface it from the
     dashboard endpoint that reads the JSON.

4. **Gate on it (optional).** Add a row to
   `eval/ci/thresholds.yaml` and a `check_min` / `check_max` call in
   `eval/ci/compare.py:54-58`.

### Verify

- A unit test under `tests/eval/` for the new metric on small
  synthetic data.
- `python -m eval.runners.run_eval --classifier baseline_noop --split test --report eval/reports/baseline.json`
  shows the new metric in the JSON.

## 8. Add a new pretrained model

**When.** Swap the embedder, reranker, or NER for a different
pretrained checkpoint.

**Background reading.** [`training.md`](training.md) §"What's *not*
trained here".

### Steps

1. **Update config.** Set `embedder_model` / `reranker_model` /
   `ner_model` in `app/config.py:13-15` (or via env var). The model
   registry will load the new checkpoint at startup.

2. **Match the dimension.** `EMBED_DIM = 384`
   (`app/db/models.py:26`) is the vector size baked into every
   `embedding` column on the schema. **A new embedder with a
   different output dim requires a schema migration plus a full
   re-embed of `hs_code`, `hs_training_example`,
   `sanctioned_commodity`, and `screening_rule`.** That's a major
   undertaking, not a config flip.

3. **Retrain the LTR.** The cross-encoder's score distribution
   shifts when its model changes, and the booster was fit on the
   old distribution. After any reranker change, run
   `POST /api/v1/training/ltr/run` before promoting to prod.

4. **Rebuild derived indexes.** A new NER model means the
   `hs_entity_index` is stale — `POST /api/v1/admin/refdata/HsEntityIndex/run`
   to rebuild.

### Verify

- `/api/v1/status/models` shows the new model identifiers, sensible
  load times, and a non-null `last_call_latency_ms`.
- `/api/v1/eval/run` against `split=test` passes the gate.
- A single `POST /api/v1/screen` returns sensible top candidates and
  the `versions` block shows the new model names.

## General rules of thumb

- **Append-only is the safe path.** New fields, new endpoints, new
  rows — easy to ship safely. Renames, reorderings, and schema
  modifications are the dangerous changes; see
  [`naming-conventions.md`](naming-conventions.md) §3 for the deferred
  rename list and the reasoning.
- **One Liquibase changeset per schema change.** Files under
  `db/changelog/changes/` are numbered; never modify a previously-
  merged changeset, always add a new one.
- **One pre-existing helper before any new code.** Before adding a
  new utility, check `app/refdata/common.py`,
  `app/refdata/sanctions/common.py`,
  `app/pipeline/retrieval/union.py`, and `eval/metrics/` — they
  already cover ~80% of the patterns you'll need.
- **Document along with the change.** Update
  [`api-reference.md`](api-reference.md),
  [`ingestion.md`](ingestion.md), or whatever doc owns the area; new
  flows deserve their own diagram.
