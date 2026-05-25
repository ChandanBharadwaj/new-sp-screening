# Commodity Screening Engine

An NLP-driven shipment commodity screening engine. Classifies free-text commodity and cargo descriptions to HS taxonomy, matches them against sanctioned-goods reference data per country pair, and scores them against semantic phrase-based rules. Emits **quantitative results only** — no allow/block/review decisions in v1.

> **Audience:** This README is written as a self-contained build specification for an autonomous engineering agent or development team building this project greenfield. It assumes no prior conversation context.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Hard Constraints](#2-hard-constraints)
3. [Scope](#3-scope)
4. [Functional Requirements](#4-functional-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Architecture Overview](#6-architecture-overview)
7. [Inference Pipeline](#7-inference-pipeline)
8. [Data Model](#8-data-model)
9. [Reference Data Sources](#9-reference-data-sources)
10. [Output Schema](#10-output-schema)
11. [Confidence Metrics](#11-confidence-metrics)
12. [Models and Algorithms](#12-models-and-algorithms)
13. [UI Requirements](#13-ui-requirements)
14. [Evaluation Harness](#14-evaluation-harness)
15. [Technology Stack](#15-technology-stack)
16. [Repository Layout](#16-repository-layout)
17. [Phased Delivery Plan](#17-phased-delivery-plan)
18. [Build Instructions for an Agent](#18-build-instructions-for-an-agent)
19. [Open Decisions](#19-open-decisions)
20. [Glossary](#20-glossary)

---

## 1. Problem Statement

Build an NLP-driven commodity screening engine that:

- Accepts shipment records containing free-text **commodity descriptions** and **cargo descriptions**, along with structured fields such as origin country, destination country, and shipment value.
- Interprets the free text and produces a **ranked, scored HS classification** at three levels: chapter (2-digit), heading (4-digit), and subheading (6-digit).
- Matches the shipment against a curated database of **sanctioned commodities** scoped by country pair, drawing from authoritative public sources (US BIS, OFAC, EU consolidated list, UN, country-specific regimes).
- Scores the shipment against **semantic phrase-based rules** authored by analysts, using meaning-based similarity rather than literal keyword match.
- Emits a **fully quantitative result** for each shipment — ranked candidates, similarity scores, score components, confidence metrics, matched records. **No categorical decision (allow / review / block) is produced in v1.** Decisioning logic is downstream and out of scope.
- Provides a **management UI** for CSV upload, result inspection with full reasoning trace, browsing HS taxonomy and sanctions reference data, authoring and testing rules, and visualizing trends.

---

## 2. Hard Constraints

These constraints are non-negotiable and shape every design decision in this document.

| # | Constraint | Implication |
|---|------------|-------------|
| C1 | **No LLM in the inference path.** No generative models (GPT, Claude, Gemma, Qwen, Llama, etc.). | All retrieval and reranking must use deterministic encoder-only models and classical IR. |
| C2 | **Quantitative output only.** No allow/review/block in v1. | Engine emits scores, confidences, ranked matches. Downstream systems decide. |
| C3 | **Inference < 1 second per shipment (p95).** | Pipeline budget ~600ms; leave headroom. Sub-second is firm. |
| C4 | **5-star accuracy.** Target: top-1 subheading ≥85%, top-3 subheading ≥95%, top-1 chapter ≥95% on a held-out gold set. | Multi-signal ensemble with cross-encoder rerank and Learning-to-Rank fusion. Evaluation harness is a Phase 0 deliverable. |
| C5 | **Explainability.** Every score must be traceable to its inputs (matched records, score components, extracted entities). | All scores returned with components, not just a final number. |
| C6 | **Free, self-hostable models only.** No paid APIs. | Use sentence-transformers, BGE, GLiNER, LightGBM — all open-source, MIT/Apache-licensed. |

---

## 3. Scope

### In scope (v1)

- HS classification of free-text commodity + cargo descriptions.
- Sanctioned-goods matching by country pair (US-export-focused initially: HTS, OFAC, BIS, EU, UN).
- Semantic rule scoring against analyst-authored phrases.
- CSV ingestion of shipments and synchronous + async screening.
- Management UI: result viewing, reference-data browsing, rule authoring, dashboards.
- Evaluation harness with CI gating on accuracy regressions.
- Feedback capture (analyst overrides) wired from day one.

### Out of scope (v1)

- Decisioning logic (allow / review / block).
- Party screening (sanctioned entities / individuals) — separate workstream, not commodity.
- LLM-based components of any kind.
- Multi-language commodity descriptions (English only in v1).
- Real-time integration with carrier or customs systems.
- Mobile UI.

### Tentative for v2+

- Decisioning engine that consumes the quantitative outputs.
- Periodic fine-tuning of the cross-encoder on accumulated analyst feedback.
- Multi-language support.
- Additional jurisdictions (UK OFSI, Japanese MOF, etc.).

---

## 4. Functional Requirements

### FR1 — HS Classification

- FR1.1 — Accept free-text commodity description and cargo description, plus optional structured fields (origin, destination, value, party metadata).
- FR1.2 — Return ranked candidates at **chapter (2-digit)**, **heading (4-digit)**, and **subheading (6-digit)** levels.
- FR1.3 — Each candidate carries a final score, individual score components (dense, sparse, entity-overlap, cross-encoder), and the HS title/description.
- FR1.4 — Support **multi-label** output: when text contains multiple distinct commodities, surface multiple high-scoring HS paths.
- FR1.5 — Reference taxonomy sourced from US HTS (USITC), US Schedule B (Census), WCO HS nomenclature, and enriched with US CBP CROSS rulings as labeled training data.

### FR2 — Sanctioned-Goods Reference Data

- FR2.1 — Maintain a normalized database of sanctioned/restricted commodities, each record carrying: source, free-text description, embedding, vector of applicable HS codes, country-pair scope, restriction type, effective dates, provenance URL.
- FR2.2 — Ingest from: US BIS Commerce Control List, US OFAC SDN + sectoral, US ITAR/USML, EU Consolidated Sanctions, EU Dual-Use Regulation Annex I, UN Consolidated List, country-specific regimes (Russia, Iran, DPRK, Syria, Cuba, Venezuela).
- FR2.3 — Country-pair constraints stored as `(origin_iso, destination_iso, sanctioned_commodity_id, restriction_type, conditions)`.
- FR2.4 — Automated refresh pipelines: sanctions weekly, HS schedule annually.

### FR3 — Semantic Rule Screening

- FR3.1 — Rules expressed as natural-language phrases (not regex, not keyword lists).
- FR3.2 — Each rule carries: name, phrase, embedding, threshold, conditions JSON (route, value, party type), action metadata (informational only in v1), active flag.
- FR3.3 — Rule matching uses semantic similarity via cross-encoder scoring between cargo text and rule phrase.
- FR3.4 — Engine emits per-rule score, threshold, and delta above/below threshold. **Does not make decisions** — reports numbers.
- FR3.5 — Composition: support any-of / all-of groupings of phrases under a single rule.
- FR3.6 — **Operator keyword lists.** Analysts can upload a CSV of sanctioned words/phrases under a named list (e.g. `seafood`). Each keyword lands in the shared `sanctioned_commodity` table (`source = "KW:<list>"`) and is materialized into one `screening_rule` per keyword, so it is scored by the same cross-encoder path as any other rule. Lists are scoped (global, or origin/destination per list) and managed entirely from the Admin UI. See [§9 — Operator keyword lists](#operator-keyword-lists).

### FR4 — Consolidated Quantitative Output

- FR4.1 — A single screening result per shipment containing: HS classification block, sanctions matches block, rule matches block, extracted entities, confidence metrics, latency telemetry.
- FR4.2 — Strict schema; downstream consumers depend on stability.
- FR4.3 — All score components retained, not collapsed into a single number.

### FR5 — Management UI

- FR5.1 — CSV upload with column mapping and async batch processing.
- FR5.2 — Results table with filtering, sorting, and drill-down to full reasoning trace.
- FR5.3 — HS taxonomy browser (tree view: chapter → heading → subheading + search).
- FR5.4 — Sanctions browser (country-pair matrix, per-commodity detail).
- FR5.5 — Rule manager (CRUD + "test phrase against sample text" preview).
- FR5.6 — Dashboards: volume by chapter, top sanction-hit reasons, country heatmaps, score distribution histograms, false-positive trending (post-feedback).
- FR5.7 — Analyst override capture: every change to a result writes a `feedback_event` row.

---

## 5. Non-Functional Requirements

| ID | Requirement | Target |
|----|-------------|--------|
| NFR1 | Single-shipment inference latency (p95) | < 1000 ms |
| NFR2 | Single-shipment inference latency (p50) | < 600 ms |
| NFR3 | Batch throughput (CSV) | ≥ 100 shipments/sec (parallelizable) |
| NFR4 | Top-1 subheading accuracy on gold set | ≥ 85% |
| NFR5 | Top-3 subheading accuracy on gold set | ≥ 95% |
| NFR6 | Top-1 chapter accuracy on gold set | ≥ 95% |
| NFR7 | Reference data freshness — sanctions | ≤ 7 days |
| NFR8 | Reference data freshness — HS taxonomy | ≤ 1 year |
| NFR9 | Result explainability | 100% of scores must have decomposable components |
| NFR10 | Determinism | Same input → same output, byte-identical |

---

## 6. Architecture Overview

The system is a **multi-signal scoring pipeline**. Each stage emits scored candidates; later stages refine; the final stage fuses signals into a ranked output. Accuracy is achieved by ensembling complementary signals — none of them an LLM.

```
┌─────────────────────────────────────────────────────────────┐
│                       UI (React)                            │
│  CSV Upload │ Results │ HS Browser │ Rules │ Dashboards     │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST
┌──────────────────────────▼──────────────────────────────────┐
│              Spring Boot Orchestrator (Java)                │
│                                                             │
│   • Screening Coordinator    • Rule Engine (scoring only)   │
│   • Decision Engine [v2]     • Audit + Feedback             │
│   • LightGBM LTR Ranker      • CSV Ingest                   │
└────┬────────────────┬──────────────────┬───────────────────-┘
     │                │                  │
     │ REST           │ SQL              │ Kafka (optional, batch)
     ▼                ▼                  ▼
┌────────────┐  ┌──────────────────┐  ┌─────────────────┐
│ Python ML  │  │ PostgreSQL +     │  │ Reference Data  │
│ Sidecar    │  │ pgvector + FTS   │  │ Ingestion Jobs  │
│ (FastAPI)  │  │                  │  │                 │
│            │  │ • hs_code        │  │ • HTS / Sch. B  │
│ • GLiNER   │  │ • sanctioned_*   │  │ • CROSS rulings │
│ • bge-small│  │ • country_rule   │  │ • OFAC / BIS    │
│ • bge-     │  │ • screening_rule │  │ • EU / UN       │
│   reranker │  │ • shipment       │  │                 │
│            │  │ • screening_     │  │                 │
│            │  │   result         │  │                 │
│            │  │ • feedback_event │  │                 │
└────────────┘  └──────────────────┘  └─────────────────┘
```

### Component responsibilities

- **Spring Boot orchestrator** — request handling, pipeline coordination, SQL access, LightGBM inference (via `lightgbm4j`), audit, feedback, CSV ingest, rule scoring orchestration.
- **Python ML sidecar (FastAPI)** — stateless model server exposing three endpoints: `/embed`, `/ner`, `/rerank`. No business logic.
- **PostgreSQL with pgvector + tsvector** — single source of truth for taxonomy, sanctions, rules, shipments, results, feedback. HNSW indexes for dense vector search; GIN indexes for BM25-style FTS.
- **Reference-data ingestion jobs** — scheduled batch jobs that pull, normalize, enrich, embed, and persist external data.

---

## 7. Inference Pipeline

End-to-end per-shipment screening, parallelizable where possible. Total budget: **~600ms p95**.

### Stage 1 — Normalization + NER (~50ms)

- Lowercase, strip stop tokens, expand common abbreviations.
- Run **GLiNER** (fine-tuned on customs entities) to extract: `material`, `form`, `end_use`, `processing_state`, `composition_percentages`, `dimensions`.
- GLiNER is a small encoder-only model (~200MB), CPU-runnable, deterministic. **Not an LLM**.
- Pass enriched text + extracted entities forward.

### Stage 2 — Hybrid Retrieval (parallel, ~150ms total)

Run three retrieval methods **concurrently** against the HS corpus:

1. **Dense vector kNN** — `BAAI/bge-small-en-v1.5` embeddings, pgvector HNSW index. Top-50 candidates.
2. **Sparse keyword retrieval** — PostgreSQL `tsvector` + GIN, BM25-ranked. Top-50 candidates.
3. **Entity-filtered structured lookup** — query `hs_entity_index` table using extracted entities (material, form, end-use). Top-50 candidates.

Union → typically 80–120 unique candidates.

### Stage 3 — Cross-Encoder Rerank (~200–400ms)

- Pass top 20–30 unioned candidates through **`BAAI/bge-reranker-v2-m3`** (or `cross-encoder/ms-marco-MiniLM-L-6-v2` as a lighter alternative).
- Cross-encoders read (query, candidate) jointly — much higher accuracy than bi-encoder cosine. **Encoder-only, no generation. Not an LLM.**
- Emit per-candidate cross-encoder score.

### Stage 4 — Feature Fusion via LightGBM (~20ms)

For each surviving candidate, build a feature vector:

| Feature | Source |
|---------|--------|
| `dense_similarity` | Stage 2 dense kNN |
| `sparse_score` | Stage 2 BM25 normalized |
| `entity_overlap_score` | Jaccard over extracted entities |
| `cross_encoder_score` | Stage 3 |
| `chapter_prior` | Frequency prior given origin/destination |
| `candidate_depth` | chapter / heading / subheading |
| `top1_minus_top2_gap` | Local separation feature |

Feed into **LightGBM Learning-to-Rank** model (trained offline on gold dataset). Output: final ranking score per candidate. **~1ms inference. Not an LLM.**

### Stage 5 — Parallel Sanctions + Rules Scoring (~150ms)

Run in parallel with HS rerank where possible:

- **Sanctions** — dense kNN + BM25 over `sanctioned_commodity` filtered by country pair; structured `(origin, dest, hs_code)` lookup against `country_rule`. Union → cross-encoder rerank top candidates → emit ranked matches with scores.
- **Rules** — fetch active rules applicable to this country pair; cross-encoder score (cargo_text, rule.phrase) per rule; evaluate structured conditions; emit per-rule scores with threshold deltas.

### Stage 6 — Output Assembly (~10ms)

Assemble structured JSON response per the schema in §10. Persist to `screening_result` table. Emit Kafka event (if batch mode).

### Latency budget summary

| Stage | Target (ms) |
|-------|-------------|
| Normalization + NER | 50 |
| Hybrid retrieval (parallel) | 150 |
| Cross-encoder rerank (HS) | 300 |
| Sanctions + rules (parallel with rerank) | 150 |
| LightGBM fusion | 20 |
| Output assembly + persist | 10 |
| **Total (p95)** | **~600** |

---

## 8. Data Model

PostgreSQL schema. All `embedding` columns are `vector(384)` (bge-small dimensionality) with HNSW indexes. All text-search columns have GIN indexes on `tsvector`.

```sql
-- HS taxonomy
CREATE TABLE hs_code (
  code              VARCHAR(10) PRIMARY KEY,
  level             SMALLINT NOT NULL,           -- 2 | 4 | 6
  parent_code       VARCHAR(10) REFERENCES hs_code(code),
  chapter           VARCHAR(2) NOT NULL,
  title             TEXT NOT NULL,
  description       TEXT,
  chapter_notes     TEXT,
  section_notes     TEXT,
  embedding         vector(384),
  description_tsv   tsvector,
  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now()
);

-- Entity index for structured lookup
CREATE TABLE hs_entity_index (
  hs_code           VARCHAR(10) REFERENCES hs_code(code),
  entity_type       VARCHAR(32),  -- material | form | end_use | processing_state
  entity_value      TEXT,
  weight            REAL,
  PRIMARY KEY (hs_code, entity_type, entity_value)
);

-- CROSS rulings and other training corpora
CREATE TABLE hs_training_example (
  id                BIGSERIAL PRIMARY KEY,
  source            VARCHAR(32) NOT NULL,  -- 'cross_ruling' | 'schedule_b' | 'analyst'
  source_id         TEXT,
  description       TEXT NOT NULL,
  hs_code           VARCHAR(10) REFERENCES hs_code(code),
  embedding         vector(384),
  description_tsv   tsvector,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Sanctioned commodities
CREATE TABLE sanctioned_commodity (
  id                BIGSERIAL PRIMARY KEY,
  source            VARCHAR(32) NOT NULL,  -- 'OFAC' | 'BIS_CCL' | 'EU_DUAL_USE' | 'UN' | ...
  source_record_id  TEXT,
  description       TEXT NOT NULL,
  hs_codes          VARCHAR(10)[],
  restriction_type  VARCHAR(32),  -- prohibited | licensed | quota | price_cap
  effective_from    DATE,
  effective_to      DATE,
  provenance_url    TEXT,
  embedding         vector(384),
  description_tsv   tsvector,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Country-pair rules over sanctioned commodities
CREATE TABLE country_rule (
  id                       BIGSERIAL PRIMARY KEY,
  origin_iso               CHAR(2),    -- nullable = any origin
  destination_iso          CHAR(2),    -- nullable = any destination
  sanctioned_commodity_id  BIGINT REFERENCES sanctioned_commodity(id),
  restriction_type         VARCHAR(32),
  conditions               JSONB,
  active                   BOOLEAN DEFAULT true,
  created_at               TIMESTAMPTZ DEFAULT now()
);

-- Analyst-authored semantic rules
CREATE TABLE screening_rule (
  id                BIGSERIAL PRIMARY KEY,
  name              TEXT NOT NULL,
  phrase            TEXT NOT NULL,
  embedding         vector(384),
  threshold         REAL NOT NULL,
  conditions        JSONB,
  origin_iso        CHAR(2),
  destination_iso   CHAR(2),
  active            BOOLEAN DEFAULT true,
  version           INT DEFAULT 1,
  created_by        TEXT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Shipments
CREATE TABLE shipment (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_ref      TEXT,
  commodity_text    TEXT NOT NULL,
  cargo_text        TEXT,
  origin_iso        CHAR(2),
  destination_iso   CHAR(2),
  shipment_value    NUMERIC(18,2),
  currency          CHAR(3),
  metadata          JSONB,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Screening results
CREATE TABLE screening_result (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  shipment_id       UUID REFERENCES shipment(id),
  hs_candidates     JSONB,         -- ranked list with score components
  sanction_matches  JSONB,
  rule_matches      JSONB,
  extracted_entities JSONB,
  confidence_metrics JSONB,
  latency_ms        JSONB,
  engine_version    TEXT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Analyst feedback
CREATE TABLE feedback_event (
  id                BIGSERIAL PRIMARY KEY,
  result_id         UUID REFERENCES screening_result(id),
  analyst_id        TEXT,
  event_type        VARCHAR(32),  -- hs_corrected | sanction_dismissed | rule_dismissed | escalated
  before_value      JSONB,
  after_value       JSONB,
  notes             TEXT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- Indexes (illustrative)
CREATE INDEX ON hs_code USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON hs_code USING gin (description_tsv);
CREATE INDEX ON hs_training_example USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON sanctioned_commodity USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON sanctioned_commodity USING gin (description_tsv);
CREATE INDEX ON screening_rule USING hnsw (embedding vector_cosine_ops);
```

---

## 9. Reference Data Sources

All free, public, authoritative. Each requires an ingestion job that pulls, normalizes, embeds, and upserts.

### HS Taxonomy

| Source | Purpose | URL | Refresh |
|--------|---------|-----|---------|
| US HTS (USITC) | 10-digit US tariff schedule with chapter/section notes | hts.usitc.gov | Annual |
| US Schedule B (Census) | Export classifications | census.gov/foreign-trade/schedules/b | Annual |
| WCO HS Nomenclature | International 6-digit root | wcoomd.org | Every 5 years |
| US CBP CROSS Rulings | Labeled (description → HS) training examples (~200k records) | rulings.cbp.gov | Quarterly |
| EU TARIC | Cross-validation, multilingual not needed for v1 | ec.europa.eu/taxation_customs | Daily (optional) |

### Sanctions / Controlled Goods

| Source | Coverage | URL | Refresh |
|--------|----------|-----|---------|
| US OFAC | SDN, sectoral sanctions | treasury.gov/ofac | Weekly |
| US BIS Commerce Control List (EAR) | ECCN-mapped dual-use goods | bis.doc.gov | Weekly |
| US ITAR / USML | Defense articles | pmddtc.state.gov | Quarterly |
| EU Consolidated Sanctions | EU regime | sanctionsmap.eu | Weekly |
| EU Dual-Use Annex I | Dual-use goods | trade.ec.europa.eu | Quarterly |
| UN Consolidated List | UN sanctions | un.org/securitycouncil | Weekly |

### Country-specific regimes (curated)

Russia (post-2022 luxury/oil/dual-use HS bans), Iran, DPRK, Syria, Cuba, Venezuela. Each requires analyst curation to map narrative restrictions to HS chapters; UI must support this.

<a name="operator-keyword-lists"></a>
### Operator keyword lists

Analyst-curated CSV lists of sanctioned words/phrases (e.g. a `seafood` list whose rows are individual restricted species). These are **not** a separate matching path — they ride on the same data and rule layers as the sources above:

- A list is a CSV with a single `keywords` column (one word/phrase per row; `keyword`/`phrase`/`phrases` headers also accepted; a UTF-8 BOM is tolerated).
- Each keyword is upserted as a `sanctioned_commodity` row with `source = "KW:<list_name>"` and a content-addressed `source_record_id` (so editing a keyword replaces it cleanly on re-upload rather than leaving a stale row). `hs_codes` is empty by default — keyword lists match semantically, not by HS overlap.
- The list's scope becomes companion `country_rule` rows: **global** (no ISO), or scoped via `direction` (`import_from` / `export_to` / `both`) with an origin/destination ISO.
- After ingest, the existing rule materializer (`app/refdata/sanctions/materialize_rules.py`) derives one `screening_rule` per keyword (`created_by = "sanctions_source:KW:<list_name>"`), embedded and scored by the cross-encoder at screen time exactly like any other rule. Materialization is auto-enabled for keyword-list sources.
- **Management is UI-only**, via Admin → Keyword lists: create a manifest (name, label, scope, threshold), upload the CSV, Run, or delete. Re-upload is a full replacement (removed keywords are orphan-deleted and their rules deactivated). `Run all ready sources` also re-ingests active lists.

| Field | Where it lives |
|-------|----------------|
| List metadata (name, scope, threshold, file path, row count) | `keyword_list` manifest table (migration `0007`) |
| Keyword content | `sanctioned_commodity` (`source = "KW:<list>"`) + `country_rule` |
| Derived semantic rule | `screening_rule` (`created_by = "sanctions_source:KW:<list>"`) |

A screening result groups fired keyword-list rules under `rule_matches_by_list` (top phrase + counts per list) alongside the standard per-rule `rule_matches`.

### First-boot data seed

`scripts/bootstrap_data.py` runs from the container entrypoint before the app comes up and downloads the **actual publisher data** (never synthesized) for sources that expose a stable direct URL — **US HTS**, **UN Consolidated**, and **OFAC SDN** (`sdn`/`add`/`alt`) — into the on-disk paths the ingesters already read. It is idempotent (skips files newer than 7 days), atomic, and best-effort (a publisher outage never blocks startup). Sources whose publishers only ship behind navigation pages, logins, or token URLs (Schedule B, WCO, BIS CCL, EU Consolidated/Dual-Use/Russia, ITAR/USML) are **reported** with their publisher URL and destination path so an operator can drop them in once. Disable per-environment with `BOOTSTRAP_ON_START=false`.

---

## 10. Output Schema

Stable JSON schema returned by `POST /api/v1/screen` and persisted in `screening_result.

```json
{
  "shipment_id": "8b1f...",
  "engine_version": "1.0.0",
  "hs_classification": {
    "top_candidates": [
      {
        "hs_code": "620462",
        "level": "subheading",
        "chapter": "62",
        "heading": "6204",
        "title": "Women's or girls' trousers, of cotton",
        "score": 0.87,
        "score_components": {
          "dense": 0.82,
          "sparse": 0.74,
          "entity_overlap": 0.91,
          "cross_encoder": 0.88,
          "chapter_prior": 0.65,
          "ltr_final": 0.87
        }
      }
    ],
    "chapter_distribution": {"62": 0.78, "61": 0.18, "52": 0.04},
    "confidence_metrics": {
      "top1_score": 0.87,
      "top1_minus_top2": 0.26,
      "entropy_topk": 0.42,
      "chapter_consensus": 0.78,
      "cross_source_agreement": true
    }
  },
  "sanction_matches": [
    {
      "source": "OFAC",
      "source_record_id": "...",
      "description": "...",
      "similarity": 0.81,
      "country_pair_applicable": true,
      "hs_code_overlap": ["620462"],
      "restriction_type": "prohibited",
      "score_components": {
        "dense": 0.79,
        "sparse": 0.71,
        "cross_encoder": 0.83,
        "structured_match": true
      }
    }
  ],
  "rule_matches": [
    {
      "rule_id": 42,
      "rule_name": "...",
      "phrase": "...",
      "phrase_similarity": 0.79,
      "threshold": 0.75,
      "delta_above_threshold": 0.04,
      "conditions_satisfied": true
    }
  ],
  "extracted_entities": {
    "material": ["cotton"],
    "form": ["woven"],
    "end_use": null,
    "processing_state": ["finished"],
    "composition_percentages": null,
    "dimensions": null
  },
  "latency_ms": {
    "ner": 47,
    "retrieval": 138,
    "rerank_hs": 312,
    "rerank_sanctions": 96,
    "rule_scoring": 84,
    "fusion": 18,
    "total": 515
  }
}
```

**Important**: there is **no** `decision`, `recommended_action`, `is_blocked`, or similar field. v1 is purely quantitative.

---

## 11. Confidence Metrics

Each defined precisely so downstream systems can reason about quality without an LLM.

| Metric | Definition | Range | Higher = |
|--------|------------|-------|----------|
| `top1_score` | Final LTR score of top candidate | [0,1] | More confident |
| `top1_minus_top2` | Score gap between top and second candidate | [0,1] | Less ambiguous |
| `entropy_topk` | Shannon entropy over normalized top-K scores | [0,log K] | More spread out (less peaky) |
| `chapter_consensus` | Fraction of top-K mass concentrated in the single highest-mass chapter | [0,1] | More agreement on chapter |
| `cross_source_agreement` | Whether dense, sparse, entity-lookup all surface the same top candidate | bool | All three agree |

---

## 12. Models and Algorithms

| Component | Model | License | Size | Notes |
|-----------|-------|---------|------|-------|
| NER | GLiNER (fine-tuned) | Apache-2.0 | ~200MB | Trained on customs entities |
| Dense embedding | `BAAI/bge-small-en-v1.5` | MIT | ~130MB, 384-dim | Stronger than MiniLM on technical text |
| Sparse retrieval | PostgreSQL FTS (`tsvector` + GIN, BM25-style) | PG license | N/A | No separate service |
| Cross-encoder rerank | `BAAI/bge-reranker-v2-m3` | Apache-2.0 | ~568MB | Or `cross-encoder/ms-marco-MiniLM-L-6-v2` for lighter |
| Feature fusion | LightGBM Learning-to-Rank | MIT | <10MB | `lambdarank` objective |

**None of these is an LLM.** All are encoder-only / classical-ML, deterministic, CPU-runnable.

### Training

- **GLiNER fine-tune** — labeled examples of customs entities from CROSS rulings + manually annotated samples. Contrastive loss.
- **Cross-encoder** — off-the-shelf for v1; fine-tune on CROSS rulings (description, hs_code) pairs as positive examples + hard negatives mined from confused chapter pairs for v1.1.
- **LightGBM LTR** — trained on gold dataset. Features = all score components. Labels = relevance grades (correct hs_code = 4, same heading = 3, same chapter = 2, same chapter family = 1, else = 0). Objective: `lambdarank`. Re-train monthly as gold dataset grows from feedback.

---

## 13. UI Requirements

React SPA. Components:

### CSV Upload
- File picker, column-mapping wizard, validation preview, async batch run with progress.
- Mapping persisted as templates per analyst.

### Results View
- Filterable, sortable table: shipment ID, top-1 HS, top-1 score, sanction match count, top rule score, country pair, created date.
- Row click → drill-down panel with full reasoning trace (every field from the output schema).
- Drill-down shows score-component breakdown for each candidate, matched entity highlights in the source text, matched sanction records with provenance URLs, matched rule phrases.
- Analyst override controls: correct HS code, dismiss sanction hit, dismiss rule hit, add note. Every override writes a `feedback_event`.

### HS Browser
- Tree view: chapter → heading → subheading. Search box with live results. Click a node to see description, chapter/section notes, embedding-near neighbors, training-example count.

### Sanctions Browser
- Country-pair matrix (origin × destination heatmap by count of active rules).
- Per-commodity detail view: description, source, HS-code overlap, country-pair applicability, provenance URL.

### Rule Manager
- CRUD list view, edit form (name, phrase, threshold, conditions JSON, country-pair scope, active flag, version).
- **Test panel**: enter sample cargo text, see live cross-encoder score against the rule phrase before saving.
- Version history per rule.

### Dashboards
- Volume by HS chapter (bar).
- Top sanction hits by source (bar).
- Country-pair heatmap of shipments.
- Score distribution histograms (top-1 HS score, top sanction similarity, top rule score).
- Trend lines for analyst-override rate per chapter (post-feedback signal).

---

## 14. Evaluation Harness

**Built in Phase 0, before any production pipeline code.** This is the most important non-product deliverable in the project.

### Components

1. **Gold dataset** — minimum 1000 manually-curated `(description → correct_hs_code)` pairs. Sources:
   - CROSS rulings (pre-labeled, sample 500).
   - Schedule B examples (pre-labeled, sample 300).
   - Analyst-curated production-like samples (200).
   Split: 70% train / 15% dev / 15% test, by chapter to avoid leakage.

2. **Metrics**:
   - Top-1 subheading accuracy
   - Top-3 subheading accuracy
   - Top-5 subheading accuracy
   - Top-1 heading accuracy
   - Top-1 chapter accuracy
   - Mean Reciprocal Rank (MRR)
   - Latency p50 / p95 / p99
   - Abstention rate vs accuracy-on-non-abstained (when confidence thresholds are applied)

3. **Confusion matrix** — at chapter level. Surfaces hard pairs (e.g., 39 vs 40, 84 vs 85, 52 vs 61 vs 62). Drives investment in targeted hard-pair classifiers.

4. **Adversarial test set** — for sanctions: paraphrased descriptions of known-restricted goods, deliberately obfuscated language, plus negative cases (similar-sounding but non-restricted). Track recall on positives and FP rate on negatives separately.

5. **CI gate** — every pull request runs the eval suite. No accuracy regression merges to main. Latency regressions block too.

6. **Continuous evaluation** — feedback events from production are sampled into the gold dataset (with secondary review) monthly.

---

## 15. Technology Stack

### Backend orchestrator
- **Java 21**, **Spring Boot 3.x**
- **Spring Data JDBC** or **R2DBC** (project preference: R2DBC, given existing skills)
- **lightgbm4j** for LTR inference in-process
- **springdoc-openapi** for API documentation
- **Resilience4j** for circuit breaking on the ML sidecar

### ML sidecar
- **Python 3.11**, **FastAPI**, **uvicorn**
- **sentence-transformers**, **transformers**, **torch** (CPU)
- **gliner** (PyPI)
- **onnxruntime** for production inference (export models to ONNX for 2–3x CPU speedup)

### Data layer
- **PostgreSQL 16+** with **pgvector** extension
- HNSW indexes on every embedding column
- GIN indexes on every `tsvector` column

### Frontend
- **React 18+**, **TypeScript**, **Vite**
- **Tailwind CSS** + a component library (project preference)
- **Recharts** for charts
- **TanStack Query** for data fetching

### Reference-data ingestion
- Scheduled jobs as Spring Boot scheduled tasks initially; promote to Kubernetes CronJobs in production.

### Observability
- Structured JSON logging (Logback + Logstash encoder)
- Micrometer + Prometheus + Grafana
- Per-stage latency histograms

### Optional / Phase 2+
- **Kafka** for async batch screening at scale.
- **MinIO / S3** for CSV storage if upload size grows.

---

## 16. Repository Layout

```
commodity-screening/
├── README.md                          # This file
├── docs/
│   ├── architecture.md
│   ├── data-model.md
│   ├── inference-pipeline.md
│   ├── evaluation-harness.md
│   └── reference-data-sources.md
│
├── backend/                           # Spring Boot orchestrator
│   ├── pom.xml
│   └── src/main/java/com/.../screening/
│       ├── api/                       # REST controllers
│       ├── pipeline/                  # Pipeline stages
│       ├── retrieval/                 # Dense / sparse / entity retrieval
│       ├── ranking/                   # LightGBM LTR wrapper
│       ├── sanctions/                 # Sanctions match path
│       ├── rules/                     # Semantic rule scoring
│       ├── feedback/                  # Feedback capture
│       ├── ingest/                    # CSV ingest
│       ├── refdata/                   # Reference-data jobs
│       └── domain/                    # Entities, repositories
│
├── ml-sidecar/                        # Python FastAPI service
│   ├── pyproject.toml
│   └── src/
│       ├── main.py                    # FastAPI app
│       ├── embed.py                   # bge-small endpoint
│       ├── ner.py                     # GLiNER endpoint
│       └── rerank.py                  # cross-encoder endpoint
│
├── frontend/                          # React SPA
│   ├── package.json
│   └── src/
│       ├── pages/
│       │   ├── Upload.tsx
│       │   ├── Results.tsx
│       │   ├── HsBrowser.tsx
│       │   ├── SanctionsBrowser.tsx
│       │   ├── RuleManager.tsx
│       │   └── Dashboards.tsx
│       └── components/
│
├── eval/                              # Evaluation harness — Phase 0
│   ├── pyproject.toml
│   ├── gold/                          # Gold datasets (JSONL)
│   ├── runners/                       # Eval scripts
│   ├── metrics/                       # Metric implementations
│   └── ci/                            # CI gating scripts
│
├── refdata-jobs/                      # Standalone ingestion scripts
│   ├── hts_ingest.py
│   ├── cross_rulings_ingest.py
│   ├── schedule_b_ingest.py
│   ├── ofac_ingest.py
│   ├── bis_ccl_ingest.py
│   ├── eu_sanctions_ingest.py
│   └── un_consolidated_ingest.py
│
├── db/
│   └── changelog/                     # Liquibase (master XML + SQL changesets)
│
├── infra/
│   ├── docker-compose.yml             # Local dev: PG + pgvector + sidecar
│   └── k8s/                           # Kubernetes manifests
│
└── .github/workflows/
    ├── backend-ci.yml
    ├── frontend-ci.yml
    ├── ml-sidecar-ci.yml
    └── eval-gate.yml                  # Blocks PR on accuracy regression
```

> **Note:** the shipped implementation is Python/FastAPI end-to-end (the orchestrator and ML models run in-process, not a separate Spring Boot service), with reference-data ingesters under `app/refdata/<source>/`. Components added since the original spec:
>
> - `app/refdata/keyword_lists/ingest.py` — operator keyword-list ingester (§9 — Operator keyword lists).
> - `scripts/bootstrap_data.py` — first-boot publisher data seed (§9 — First-boot data seed).
> - `db/changelog/changes/0007-keyword-lists.sql` — `keyword_list` manifest table.
> - `frontend/src/components/admin/KeywordListPanel.vue` + the Admin "Keyword lists" section.

---

## 17. Phased Delivery Plan

### Phase 0 — Foundations (2–3 weeks)

**Goal**: nothing ships until eval can measure it.

- Repo scaffolding per §16.
- Local dev infra (docker-compose): PostgreSQL + pgvector, Python sidecar stub, Spring Boot stub.
- Database migrations for full schema (§8).
- Gold dataset assembly: 1000 labeled `(text → hs_code)` pairs.
- Eval harness: metrics, runners, CI gate. Baseline numbers from a no-op classifier.

### Phase 1 — HS Classification (6–8 weeks)

- Reference-data ingestion: HTS, Schedule B, CROSS rulings.
- Embedding generation pipeline: bge-small over all HS codes + training examples.
- ML sidecar: `/embed`, `/ner`, `/rerank` endpoints.
- Backend pipeline stages: normalization, NER, hybrid retrieval, cross-encoder rerank.
- LightGBM LTR training pipeline + inference integration.
- HS classification API (`POST /api/v1/classify`).
- Minimal UI: CSV upload + result table + HS browser.
- **Ship when eval clears**: top-1 subheading ≥85%, top-3 subheading ≥95%, top-1 chapter ≥95%, p95 latency <1s.

### Phase 2 — Sanctions (4–6 weeks)

- Sanctions ingestion: OFAC, BIS CCL, EU consolidated, EU dual-use, UN.
- Country-rule curation UI.
- Dual-path sanctions matching (structured + semantic) integrated into pipeline.
- Sanctions browser UI (country-pair matrix + detail view).
- Adversarial sanctions eval set.

### Phase 3 — Rules (3–4 weeks)

- Semantic rule data model + CRUD API.
- Rule scoring integrated into pipeline.
- Rule manager UI with test-against-sample preview.
- Rule eval harness (separate from HS eval).

### Phase 4 — Feedback + Dashboards (3–4 weeks)

- Analyst override capture in UI → `feedback_event` writes.
- Dashboard pages.
- Monthly feedback → gold-set sampling job.
- Re-training scripts for cross-encoder and LTR ranker.

### Phase 5 — Hardening (ongoing)

- Performance tuning: HNSW parameters, BM25 k1/b, batch sizes, ONNX export.
- Hard-pair classifier additions based on confusion-matrix data.
- Reference-data refresh automation.

---

## 18. Build Instructions for an Agent

This section gives an autonomous agent (or developer) the concrete steps to build the project from a clean checkout. **Execute phases sequentially. Do not skip Phase 0.**

### Step 1 — Repository scaffolding
1. Create the directory tree per §16.
2. Initialize Spring Boot project (Java 21, Maven, dependencies: spring-boot-starter-web, spring-boot-starter-data-r2dbc, r2dbc-postgresql, springdoc-openapi, lightgbm4j, resilience4j-spring-boot3).
3. Initialize Python sidecar (FastAPI, uvicorn, sentence-transformers, transformers, torch, gliner, onnxruntime).
4. Initialize React frontend (Vite + TypeScript + Tailwind + Recharts + TanStack Query).
5. Initialize eval harness as a separate Python project under `eval/`.
6. Add docker-compose for PostgreSQL 16 + pgvector extension.

### Step 2 — Database
1. Schema is managed by Liquibase (`db/changelog/db.changelog-master.xml`).
2. The app container runs `liquibase update` from its entrypoint on startup, which installs the `vector`, `pg_trgm`, and `pgcrypto` extensions, creates all tables, and builds the HNSW + GIN indexes. To run it by hand: `liquibase --defaults-file=liquibase.properties --url=jdbc:postgresql://localhost:5432/screening --username=screening --password=screening update`.

### Step 3 — Eval harness (Phase 0)
1. Build CROSS rulings parser: scrape or download bulk export, parse into `(description, hs_code)` JSONL.
2. Build Schedule B parser: download CSV from Census, parse into `(description, hs_code)` JSONL.
3. Hand-curate 200 production-like samples.
4. Stratified split: 70/15/15 by chapter.
5. Implement metrics module (top-K accuracy, MRR, latency percentiles, confusion matrix).
6. Implement no-op baseline classifier (returns chapter 99 always).
7. Run eval, record baseline numbers, commit gold set + baseline report.
8. Wire CI: PR must run eval and not regress beyond a tolerance band.

### Step 4 — Reference data ingestion (Phase 1 start)
1. **HTS ingest**: download annual HTS JSON, parse into `hs_code` rows at levels 2, 4, 6. Include chapter and section notes.
2. **CROSS rulings ingest**: parse the bulk export into `hs_training_example` rows.
3. **Schedule B ingest**: parse into additional `hs_training_example` rows.
4. Verify counts: ~5000 HS codes at level 6, ~200k+ training examples.

### Step 5 — Embeddings + ML sidecar
1. Implement `/embed` endpoint: input list of texts → list of 384-dim vectors. Model: `BAAI/bge-small-en-v1.5`.
2. Implement `/ner` endpoint: input text → extracted entities. Model: GLiNER (off-the-shelf for v1).
3. Implement `/rerank` endpoint: input (query, list of candidates) → list of relevance scores. Model: `BAAI/bge-reranker-v2-m3`.
4. Batch-embed all `hs_code.description` and `hs_training_example.description` rows.
5. Verify HNSW index works: a sanity-check nearest-neighbor query returns sensible results.

### Step 6 — Hybrid retrieval
1. Implement `DenseRetriever` (Spring Boot): given query embedding, kNN top-50 from `hs_code` and from `hs_training_example`.
2. Implement `SparseRetriever`: PostgreSQL `ts_rank_cd` over `description_tsv` for top-50.
3. Implement `EntityRetriever`: given extracted entities, query `hs_entity_index`, aggregate to top-50 HS codes.
4. Implement union + dedup logic.

### Step 7 — Cross-encoder rerank
1. Call `/rerank` for top 20–30 unioned candidates.
2. Wire scores into the candidate objects.

### Step 8 — LightGBM LTR
1. Generate training data: for each gold-set example, run hybrid retrieval, collect features for each candidate, label relevance.
2. Train LightGBM with `lambdarank` objective.
3. Serialize model. Load in Spring Boot via lightgbm4j.
4. Apply to ranked candidates as the final fusion step.

### Step 9 — Confidence metrics + output assembly
1. Compute the metrics in §11.
2. Assemble response per §10.
3. Persist to `screening_result`.

### Step 10 — API + minimal UI
1. `POST /api/v1/screen` — single shipment screening.
2. `POST /api/v1/batch/upload` — CSV ingest, async processing.
3. `GET /api/v1/results` — paginated, filterable.
4. `GET /api/v1/hs/{code}` — taxonomy detail.
5. Frontend pages: Upload, Results, HS Browser (in that order).

### Step 11 — Eval gate
1. Run full eval. Verify targets per §17 Phase 1.
2. If not met: iterate on cross-encoder fine-tuning, paraphrase enrichment from CROSS rulings, hard-pair classifier additions.
3. Do **not** proceed to Phase 2 until eval is green.

### Step 12 — Phases 2–5
Follow §17.

---

## 19. Open Decisions

These should be locked by stakeholders before or during early Phase 1.

| # | Decision | Default Recommendation |
|---|----------|------------------------|
| D1 | Exact accuracy targets (gating Phase 1 ship) | Top-1 subheading ≥85%, top-3 ≥95%, top-1 chapter ≥95% |
| D2 | Geographic scope of v1 | US-export-focused: HTS + Schedule B + OFAC + BIS + EU + UN |
| D3 | Cross-encoder: off-the-shelf or fine-tune for v1 | Off-the-shelf for v1; fine-tune for v1.1 |
| D4 | Hard-pair classifier strategy | Reactive — let confusion matrix drive investment |
| D5 | Synchronous vs async API surface | Both — sync `/screen`, async batch via CSV |
| D6 | Reference-data refresh automation | Spring `@Scheduled` initially; K8s CronJobs in prod |
| D7 | ONNX export timing | After Phase 1 ships, before Phase 2 |
| D8 | Analyst-override UX shape | TBD with UX design partner |

---

## 20. Glossary

| Term | Definition |
|------|------------|
| **HS code** | Harmonized System code — international standard for classifying traded goods. 2-digit chapter, 4-digit heading, 6-digit subheading (international); national systems extend to 8 or 10 digits. |
| **HTS** | Harmonized Tariff Schedule of the United States. 10-digit US-specific extension of HS. |
| **Schedule B** | US Census Bureau export classification, 10-digit, HS-aligned. |
| **CROSS** | US Customs Rulings Online Search System — searchable database of binding HS classification rulings. |
| **CCL / EAR** | Commerce Control List under the Export Administration Regulations, maintained by US BIS. |
| **ECCN** | Export Control Classification Number — identifier on the CCL. |
| **OFAC** | Office of Foreign Assets Control — US Treasury sanctions authority. |
| **SDN** | Specially Designated Nationals list — OFAC's primary sanctions list. |
| **ITAR / USML** | International Traffic in Arms Regulations / US Munitions List — US defense-article controls. |
| **GLiNER** | A general-purpose NER architecture using encoder models; small, fast, fine-tunable, not an LLM. |
| **BM25** | Classical sparse retrieval ranking function — TF-IDF variant used by Lucene/Postgres FTS. |
| **HNSW** | Hierarchical Navigable Small World — graph-based approximate nearest-neighbor index used by pgvector. |
| **Cross-encoder** | Transformer model that reads (query, candidate) jointly to produce a relevance score. Higher accuracy, slower than bi-encoders. Not generative. |
| **Bi-encoder** | Transformer model that encodes query and candidate independently into vectors; similarity via cosine. Fast, lower accuracy than cross-encoder. |
| **LTR** | Learning-to-Rank — supervised ML on ranking problems. LightGBM `lambdarank` is the standard implementation. |
| **MRR** | Mean Reciprocal Rank — ranking quality metric: mean of `1/rank_of_first_correct`. |
| **pgvector** | PostgreSQL extension for vector storage and ANN search. |

---

**End of specification.** Every requirement, constraint, model choice, data source, schema, and phase boundary needed to build the v1 commodity screening engine greenfield is captured above. The accompanying agent instructions in §18 are designed to be executed sequentially without reference to outside context.
