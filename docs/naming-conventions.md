# Naming conventions

Three sections: conventions the codebase already follows, the canonical
glossary of domain terms, and proposed canonical names where the current
code is inconsistent. **Renames are not in scope here** — this is the
reference an onboarding engineer should read before adding new modules or
fields.

## 1. Conventions currently followed

### Module layout

```
app/
├── api/                    # FastAPI routers; one file per resource:
│                           #   routes_<resource>.py (routes_screen.py, routes_eval.py, ...)
├── pipeline/               # Inference stages; one module per stage.
│   ├── orchestrator.py     # Ties stages together.
│   ├── normalize.py · ner.py · decompose.py · rerank.py · fusion.py
│   ├── sanctions.py · rules.py · confidence.py · assemble.py · versions.py
│   └── retrieval/          # The three retrieval branches + union.
│       └── dense.py · sparse.py · entity.py · union.py
├── refdata/                # Ingestion. One subpackage per source.
│   ├── common.py           # with_run_logging, mark_progress, update_tsv_for_table.
│   └── <category>/<source>/
│       ├── ingest.py       # async def main_async(...)  ← uniform entry point
│       ├── parser.py       # optional: source-specific parsing
│       └── scraper.py      # optional: web scrape
├── models/                 # Model wrappers loaded once at process start.
│   ├── registry.py         # ModelRegistry + load_models() singleton
│   └── embedder.py · reranker.py · ner_model.py · ltr.py
├── schemas/                # Pydantic request/response schemas.
├── db/                     # SQLAlchemy mappers + session factory.
├── training/               # ltr_dataset.py (build dataset), ltr_train.py (fit booster)
└── workers/                # arq jobs; one file per job family.
                            #   refdata_jobs.py · training_jobs.py · eval_jobs.py · batch_screen.py
eval/
├── gold/                   # Gold-set splits (real-data only; built by GoldAssembly).
├── runners/                # Pluggable eval classifiers + run_eval.py
├── metrics/                # ranking.py, latency.py, confusion.py
└── ci/                     # compare.py + thresholds.yaml (PR gate)
```

### Function-level conventions

- **Async ingester entry point**: `async def main_async(...)` in every
  `app/refdata/**/ingest.py`. `app/workers/refdata_jobs.py:34-112` dispatches
  to these by `source` string.
- **Reusable runner / job pattern**: each long-running job exposes a single
  `async def <job_name>(ctx, params)` in `app/workers/`. CLI scripts call
  the same library entry point (`build_dataset`, `fit_booster`, `run`).
- **DB row updaters mid-run**: use `await mark_progress(db, run, rows)` from
  `app/refdata/common.py:75-85` so the Status UI sees progress before
  completion.
- **Cross-cutting helpers** that operate on the canonical sanctioned-commodity
  shape live in `app/refdata/sanctions/common.py` —
  `upsert_sanctioned_commodities`, `expand_hs_prefixes`, `insert_aliases`,
  `normalize_cn_code`. New sanctions ingesters should reuse these rather
  than roll their own upsert.

### Variable / field naming

Stable conventions inside `app/pipeline/`:

- Score signals are suffixed `_score` or `_similarity`:
  `dense_similarity`, `sparse_score`, `entity_overlap_score`,
  `cross_encoder_score`, `rrf_score`. See `app/pipeline/retrieval/union.py:23`
  for the canonical `NUMERIC_FIELDS` tuple — keep new signals in line with
  that list.
- The fused, end-of-pipeline number is `score` (`app/pipeline/fusion.py:64`).
- Confidence metrics use stable snake_case names defined in
  `app/schemas/screen.py:28-33`: `top1_score`, `top1_minus_top2`,
  `entropy_topk`, `chapter_consensus`, `cross_source_agreement`.
- Database tables and columns are snake_case singular (`sanctioned_commodity`,
  `country_rule`, `screening_rule`). Constraint names are
  `uq_<table>_<columns>` (`uq_sanctioned_commodity_source_recid`,
  `uq_country_rule`, `uq_alias_per_commodity`).
- ISO 3166-1 alpha-2 country codes are `origin_iso` / `destination_iso`
  (CHAR(2)). Don't introduce `from_country` or `country_to` variants.

## 2. Domain glossary

| Domain concept | Canonical term | Where it lives | Currently appears as |
|---|---|---|---|
| Input shipment payload | `ShipmentIn` | `app/schemas/screen.py:7` | consistent |
| A retrieved HS code result | `HsCandidate` | `app/schemas/screen.py:18` (response) and dicts inside `app/pipeline/` | Pydantic `HsCandidate` at the boundary; plain `dict` (referred to as `c` / `cand` / `candidate` / `cands`) inside the pipeline |
| Score breakdown on a candidate | `score_components` | `app/pipeline/fusion.py:56` | consistent |
| Confidence summary | `ConfidenceMetrics` | `app/schemas/screen.py:28` | consistent |
| HS classification block | `HsClassification` | `app/schemas/screen.py:36` | consistent |
| Final response envelope | `ScreeningResultOut` | `app/schemas/screen.py:49` | consistent |
| A sanctions reference row (the regulated good, not the party) | **proposed**: `SanctionedItem` | `app/db/models.py:74 SanctionedCommodity` | legacy name `SanctionedCommodity` |
| An alias / AKA for a sanctioned entity | `SanctionedCommodityAlias` | `app/db/models.py:119` | consistent |
| A country-pair restriction row | `CountryRule` | `app/db/models.py:97` | consistent |
| A sanctions hit on a screening | `sanction_match` | `app/pipeline/sanctions.py:369-388` (dict shape) | also called "hit" in some log lines and comments |
| A rule hit on a screening | `rule_match` | `app/pipeline/rules.py:133-146` (dict shape) | consistent |
| A retrieval branch result | `<branch>_score` / `<branch>_similarity` | retrieval modules | mixed: `dense_similarity`, `sparse_score`, `entity_overlap_score`, `cross_encoder_score`, `rrf_score` |
| Stored shipment | `Shipment` | `app/db/models.py:164` | consistent |
| Stored screening | `ScreeningResult` | `app/db/models.py:178` | consistent |
| Refdata ingestion run | `RefdataRun` | `app/db/models.py:211` | consistent |
| Training run | `TrainingRun` | `app/db/models.py:264` | consistent |
| Eval offline run | `EvalRun` (metric row) + `EvalJob` (worker state) | `app/db/models.py:223, 278` | distinct; **EvalRun = metrics**, **EvalJob = worker lifecycle** |
| Batch screening job | `BatchJob` + `BatchJobError` | `app/db/models.py:240, 252` | consistent |
| Per-job streamed log line | `JobLog` | `app/db/models.py:291` | consistent |

## 3. Proposed canonical names (deferred renames)

Each of these is an inconsistency or an outright misnomer. The cost of
renaming is given so future contributors can weigh it against the value.

### 3.1 `SanctionedCommodity` → `SanctionedItem`

**Why.** The table holds *anything* the regulators publish: dual-use parts,
ECCN-coded items, country-program prohibited categories, and OFAC SDN
*parties* with empty `hs_codes` (per `docs/sanctions-sources.md`, OFAC is
out-of-scope for goods records). Calling all of these "commodities" is
inaccurate — entity rows aren't commodities. `SanctionedItem` is neutral.

**Cost.** ~40 Python references (mostly in `app/refdata/sanctions/**` and
`app/pipeline/sanctions.py`), one DB table rename + a SQLAlchemy mapper
change, FK columns in `country_rule.sanctioned_commodity_id` and
`sanctioned_commodity_alias.sanctioned_commodity_id`, plus the unique
constraint `uq_sanctioned_commodity_source_recid`. Defer until a major
schema bump that already requires a Liquibase migration. Until then, the
ORM model is `SanctionedCommodity` and that *is* the canonical name in
code.

### 3.2 "hit" → "match"

**Why.** Sanctions and rules surface as `sanction_matches` and `rule_matches`
in the response payload (`app/schemas/screen.py:53-54`). Internal docstrings
and log lines occasionally call these "hits", which doesn't match the wire
shape and creates ambiguous diff comments.

**Cost.** Comment / log-string only. Safe to rename incrementally without a
migration. Until then: **"match" is the canonical term** for both wire and
prose.

### 3.3 `candidate` (HS) vs `match` (sanctions / rule)

**Why.** Confusable but intentionally distinct:

- A **candidate** is a row in `hs_classification.top_candidates`: the engine
  is *proposing* HS codes. There is always exactly one ranked list per
  screening (plus an optional `multi_commodity` list per fragment).
- A **match** is a row in `sanction_matches` / `rule_matches`: a hit
  against an existing reference record. There can be zero, one, or many,
  and they aren't ranked into a single "best" answer the way candidates
  are.

**Cost.** None — keep the distinction. Documented here so the next reader
doesn't paper over it with a refactor.

### 3.4 Score-signal field names

**Why.** Today the retrieval branches use a mix of suffixes
(`dense_similarity` vs `sparse_score` vs `entity_overlap_score` vs
`cross_encoder_score` vs `rrf_score`). For consumers writing fusion features
the inconsistency is a small papercut.

**Proposed.** Suffix every retrieval-branch numeric with `_score` and let
the embedder-specific term `_similarity` survive only on the dense path
(because it really is a cosine similarity, not a normalized score).

**Cost.** Renaming a feature column requires a coordinated change to:
`app/pipeline/retrieval/{dense,sparse,entity,union}.py`,
`app/pipeline/rerank.py`, `app/pipeline/fusion.py`,
`app/models/ltr.py:FEATURE_ORDER`, **and** retraining the LightGBM booster
so the new feature order matches. Don't do this opportunistically; bundle
it with the next training cycle.

### 3.5 `metadata` JSON column on `shipment`

**Why.** The SQLAlchemy attribute is `metadata_json` because `metadata` is a
reserved name on the declarative base
(`app/db/models.py:174 metadata_json: ... = mapped_column("metadata", JSONB)`).
The wire shape stays `metadata` (mapped by the column name override). New
code that touches the model must use `Shipment.metadata_json` even though
the underlying column and request field are `metadata`.

### 3.6 `engine_version` vs `versions`

**Why.** A screening result carries both:

- `engine_version` (string) — the value of `settings.engine_version`, the
  short semver of the running app.
- `versions` (dict) — the full snapshot built by `app/pipeline/versions.py`:
  engine, embedder, reranker, NER, LTR file hash, and a per-source
  `refdata` map of last-successful ingest timestamps.

**Keep both.** `engine_version` is the human-readable label that goes into
logs and dashboards; `versions` is the structured snapshot for replay /
debugging. Don't drop the redundancy.

---

## Quick reference: when adding new code

- New refdata source → create `app/refdata/<category>/<source>/ingest.py`
  with `async def main_async(...)`. Add a branch to
  `app/workers/refdata_jobs.py:run_refdata`. Reuse
  `with_run_logging` and `upsert_sanctioned_commodities` (or the
  category's equivalent helper).
- New pipeline signal → add a `_score` field on the candidate dict in the
  relevant retrieval branch, declare it in
  `app/pipeline/retrieval/union.py:NUMERIC_FIELDS`, append it to
  `app/models/ltr.py:FEATURE_ORDER`, and retrain before deploy.
- New API endpoint → create `app/api/routes_<resource>.py`, include the
  router in `app/main.py`.
- New worker job → create `app/workers/<family>_jobs.py`, expose
  `async def <job_name>(ctx, params)`, register it in
  `app/workers/arq_app.py`.
