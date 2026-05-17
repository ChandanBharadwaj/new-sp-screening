# End-to-end data flow: one shipment, ingestion to outcome

This doc traces a single, realistic shipment through every stage of the
system. It complements [`inference.md`](inference.md) by attaching
*concrete data* to each stage. The HS codes, scores, and sanction
matches below are illustrative but consistent with how the production
pipeline behaves on this kind of input — they are not the result of
running the pipeline live in this session.

The example is a dual-use semiconductor shipment from Japan to Russia.
It exercises every interesting branch: a confident-but-ambiguous HS
classification, multiple parallel sanctions paths (structured + dense +
sparse + alias), and a rule match on shipment value.

## 0. Pre-flight — what ingestion already wrote

Before any screening can run, the refdata flow has populated the
database. For this example the relevant rows are:

- **`hs_code`** — at least the 6-digit subheadings under chapters 28
  (inorganic chemistry), 38 (chemical preparations), 84 (machinery),
  85 (electronics), 90 (optical/measuring instruments).
  Source: `HTS` and `WCO` ingesters.
- **`hs_training_example`** — historical CROSS rulings on silicon
  products and semiconductor equipment, plus Schedule B descriptions.
- **`hs_entity_index`** — derived by GLiNER over `hs_code`. For our
  example the salient entries include:

  ```text
  hs_code   entity_type   entity_value     weight
  ───────── ───────────── ──────────────── ──────
  381800    material      silicon          0.91
  381800    form          doped            0.84
  381800    end_use       electronics      0.77
  854231    product       ic               0.88
  854110    product       diode            0.79
  901041    end_use       lithography      0.86
  ```

- **`sanctioned_commodity`** + **`country_rule`** — sample rows the
  inference stage will match against:

  ```text
  id   source        source_record_id    description                                hs_codes
  ──── ───────────── ─────────────────── ─────────────────────────────────────────  ─────────
  1041 EU_RUSSIA     ANNEX_VII_28461010  "Doped chemical elements for electronics" {381800}
  1042 EU_RUSSIA     ANNEX_VII_85423190  "Electronic integrated circuits"          {854231,854232,854233}
  1043 BIS_CCL       ECCN_3C001          "Hetero-epitaxial materials (Si/Ge)"      {381800,854110}
  1044 BIS_CCL       ECCN_3B001          "Equipment for lithographic processes"    {901041}

  origin_iso destination_iso sanctioned_commodity_id  restriction_type
  ────────── ─────────────── ───────────────────────  ─────────────────
  NULL       RU              1041                     prohibited
  NULL       RU              1042                     prohibited
  NULL       RU              1043                     license_required
  NULL       RU              1044                     license_required
  ```

- **`screening_rule`** — at least one rule applicable to this route:

  ```text
  id  name                                   phrase                         conditions
  ──  ────────────────────────────────────── ─────────────────────────────  ───────────────────────────────────
  17  "High-value dual-use to RU/BY"         "dual-use semiconductor or     {"min_value": 100000,
                                              lithography equipment"         "destination_iso": "RU"}
  ```

The `versions` block stamped on the response will record the last
successful ingest timestamp per source, so the screening is reproducible
even if refdata is refreshed later.

## 1. Request

A client `POST`s to `/api/v1/screen`:

```json
{
  "external_ref": "JP-RU-2026-0517-001",
  "commodity_text": "Silicon wafers, 300mm, EUV photoresist coating, semiconductor manufacturing equipment spares",
  "cargo_text": "5 pallets, lithography consumables",
  "origin_iso": "JP",
  "destination_iso": "RU",
  "shipment_value": 480000,
  "currency": "USD",
  "metadata": {"incoterm": "FOB", "carrier": "ANA Cargo"}
}
```

Validated by `ShipmentIn` (`app/schemas/screen.py:7`), then passed into
`orchestrator.run_screen` (`app/pipeline/orchestrator.py:53`).

## 2. Normalize (stage 1)

Concatenated raw text (`commodity_text + " " + cargo_text`):

```text
Silicon wafers, 300mm, EUV photoresist coating, semiconductor manufacturing equipment spares 5 pallets, lithography consumables
```

`normalize.normalize` (`app/pipeline/normalize.py:29`):

- lowercase
- strip non-word punctuation (`,` kept; `,` → ` `)
- apply abbreviation map (no hits here — none of "w/", "pcs", "mfg" appear in surface form because the input is already spelled out)
- drop stop tokens (`the`, `a`, `an`, `of`, `for`, `to`, `and`, `or`, `with`)
- collapse whitespace

Result (`norm`):

```text
silicon wafers 300mm euv photoresist coating semiconductor manufacturing equipment spares 5 pallets lithography consumables
```

## 3. NER (stage 2)

`ner.extract(model, norm)` (`app/pipeline/ner.py:6`) returns the structured form;
`flatten_to_text` strips spans for downstream:

```python
# structured (kept for the UI and the persisted ScreeningResult)
{
  "material":    [{"text": "silicon",      "start":  0, "end":  7, "score": 0.94}],
  "product":     [{"text": "wafers",       "start":  8, "end": 14, "score": 0.91},
                  {"text": "photoresist",  "start": 27, "end": 38, "score": 0.86},
                  {"text": "lithography",  "start":107, "end":118, "score": 0.88}],
  "measurement": [{"text": "300mm",        "start": 15, "end": 20, "score": 0.83}],
  "end_use":     [{"text": "semiconductor manufacturing", "start": 50, "end": 76, "score": 0.79}],
  "form":        [{"text": "coating",      "start": 39, "end": 46, "score": 0.71}]
}

# flat (used by retrieval and the decomposer)
{
  "material":    ["silicon"],
  "product":     ["wafers", "photoresist", "lithography"],
  "measurement": ["300mm"],
  "end_use":     ["semiconductor manufacturing"],
  "form":        ["coating"]
}
```

## 4. Decompose (stage 3)

`decompose.split_into_commodities(norm, entities_flat)`
(`app/pipeline/decompose.py:71`):

- The text contains no `+`, `&`, `;`, ` plus `, or `/` separators between
  alpha tokens. The `_SPLIT_RE` yields a single fragment.
- The comma-fallback yields four fragments, but only one distinct
  material token (`silicon`) appears across them — the
  `distinct_materials < 2` guard at `:102` fires.
- Returns `Decomposition(fragments=[CommodityFragment(text=norm, materials=["silicon"])], confidence=0.0)`.

The orchestrator's gate at `:96` (`confidence >= 0.5` AND
`len(fragments) >= 2`) is **not** satisfied. The single-commodity path
continues; no per-fragment re-rank.

## 5. HS ranking (stage 4)

### 5a. Dense — `retrieval/dense.py:40`

BGE-small encodes the query with the asymmetric prefix and HNSW search
over `hs_code` and `hs_training_example` runs in parallel. Top-5 from
`hs_code` (the taxonomy):

```text
hs_code  chapter  title                                                     dense_similarity
───────  ───────  ────────────────────────────────────────────────────────  ────────────────
381800   38       "Chemical elements doped for use in electronics..."       0.78
854231   85       "Electronic integrated circuits — processors and ctrl."   0.73
901041   90       "Photoresists and other materials for use in semicond."   0.71
854110   85       "Diodes other than photosensitive or LEDs"                0.67
382499   38       "Chemical preparations of chemical industries, n.e.s."    0.62
```

`hs_training_example` contributes `dense_via_training` for any code with
a matching CROSS ruling (often `0.85` for codes seen verbatim, slightly
discounted at `:76`).

### 5b. Sparse — `retrieval/sparse.py:29`

`plainto_tsquery('english', ...)` of the normalized text, `ts_rank_cd`:

```text
hs_code  sparse_score (normalized to [0,1])
───────  ──────────────────────────────────
854231   0.81   "electronic integrated circuits"  ← strong lexical hit on "integrated", "semiconductor"
854110   0.62   "diodes" — lexical "semiconductor"
901041   0.58   "photoresists" matches the surface form
381800   0.49   "chemical elements doped" — weaker word overlap with input
```

### 5c. Entity — `retrieval/entity.py:28`

Joins the flat entities against `hs_entity_index`. Pairs in our example
that exist in the index:

```text
(material, silicon)       → hits 381800 (w=0.91)
(form, doped)             → no hit (we don't have "doped" in NER; surface form was "coating")
(product, wafers)         → hits 381800 (w=0.75), 854110 (w=0.40)
(end_use, electronics)    → hits 381800 (w=0.77), 854231 (w=0.55)
(product, lithography)    → hits 901041 (w=0.86)
```

Sum + max-normalize:

```text
hs_code  entity_overlap_score
───────  ────────────────────
381800   1.00   (silicon + wafers + electronics)
901041   0.65
854231   0.42
854110   0.30
```

### 5d. Union — `retrieval/union.py:49`

`fusion_mode = "rrf"`, `rrf_k = 60`. Merged candidate dicts preserve
per-source scores **and** accumulate `rrf_score` from each branch's
rank position:

```text
hs_code  dense  sparse  entity  rrf_score
───────  ─────  ──────  ──────  ─────────
381800   0.78   0.49    1.00    0.0492   (rank 1+4+1)
854231   0.73   0.81    0.42    0.0488   (rank 2+1+3)
901041   0.71   0.58    0.65    0.0476   (rank 3+3+2)
854110   0.67   0.62    0.30    0.0461   (rank 4+2+4)
382499   0.62   0.34    0.10    0.0394   (rank 5+5+5)
```

(Exact RRF values depend on the rank in each source; the relative
ordering is what matters for the next stage.)

### 5e. Cross-encoder rerank — `pipeline/rerank.py:37`

The top-20 (`settings.rerank_top_k`) are scored by the BGE reranker
against the candidate text built by `_candidate_text` (`:5-19`):

```text
hs_code  candidate_text passed to reranker
───────  ──────────────────────────────────────────────────────────────────────────
381800   "HS 381800 (ch 38): chemical elements doped for use in electronics..."
854231   "HS 854231 (ch 85): electronic integrated circuits — processors..."
901041   "HS 901041 (ch 90): photoresists and other materials for use in..."
854110   "HS 854110 (ch 85): diodes other than photosensitive or LEDs"
...
```

Sigmoid-squashed reranker logits:

```text
hs_code  cross_encoder_score
───────  ───────────────────
381800   0.86
901041   0.74
854231   0.61
854110   0.42
382499   0.18
```

The cross-encoder pulls `381800` decisively to the top because the
candidate's surface form ("silicon… doped… electronics") matches the
query's material + end-use signals better than the IC code does.

### 5f. LightGBM fusion — `pipeline/fusion.py:25`

Features per candidate (`FEATURE_ORDER` from `app/models/ltr.py:10-18`):

```text
hs_code  dense  sparse  entity  cross  chapter_prior  candidate_depth  top1_minus_top2_gap
───────  ─────  ──────  ──────  ─────  ─────────────  ───────────────  ───────────────────
381800   0.78   0.49    1.00    0.86   0.32           6.0              0.12
854231   0.73   0.81    0.42    0.61   0.27           6.0              0.12
901041   0.71   0.58    0.65    0.74   0.18           6.0              0.12
854110   0.67   0.62    0.30    0.42   0.27           6.0              0.12
382499   0.62   0.34    0.10    0.18   0.32           6.0              0.12
```

(`chapter_prior` is the mass of each chapter in the merged candidate
list; `top1_minus_top2_gap` is computed *over the candidate list* and
broadcast — it's a feature about the *list*, not the row.)

`ltr.predict(...)` returns the booster's score per row; the
orchestrator sorts:

```text
rank  hs_code  score   score_components
────  ───────  ──────  ────────────────────────────────────────────────────────────────────────────
1     381800   0.71    dense=0.78  sparse=0.49  entity_overlap=1.00  cross_encoder=0.86  ltr_final=0.71
2     901041   0.66    dense=0.71  sparse=0.58  entity_overlap=0.65  cross_encoder=0.74  ltr_final=0.66
3     854231   0.64    dense=0.73  sparse=0.81  entity_overlap=0.42  cross_encoder=0.61  ltr_final=0.64
4     854110   0.48    ...
5     382499   0.22    ...
```

## 6. Sanctions match (stage 5)

`sanctions.score(...)` (`app/pipeline/sanctions.py:171`) runs the four
paths in parallel:

### Structured

```sql
JOIN country_rule cr ON cr.sanctioned_commodity_id = sc.id
WHERE cr.active = true
  AND (cr.origin_iso IS NULL OR cr.origin_iso = 'JP')
  AND (cr.destination_iso IS NULL OR cr.destination_iso = 'RU')
  AND sc.hs_codes && ARRAY['381800','901041','854231','854110','382499',...]
```

Hits:

```text
id    source     description                                  hs_codes  restriction_type
────  ─────────  ───────────────────────────────────────────  ────────  ─────────────────
1041  EU_RUSSIA  "Doped chemical elements for electronics"    {381800}  prohibited
1042  EU_RUSSIA  "Electronic integrated circuits"             {854231,…} prohibited
1043  BIS_CCL    "Hetero-epitaxial materials (Si/Ge)"         {381800,854110} license_required
1044  BIS_CCL    "Equipment for lithographic processes"       {901041}  license_required
```

### Dense

pgvector cosine against `sanctioned_commodity.embedding` filtered to
records whose country_rule scope is compatible with JP→RU. Top hits
overlap with the structured set (1041–1044) plus some lower-similarity
matches.

### Sparse

`ts_rank_cd` against `description_tsv` — surfaces `1044` (the keyword
"lithography" hits hard) and `1042` ("integrated circuits").

### Alias trigram

`normalize_party(query_text)` returns nothing party-like — the input is
goods, not a named entity — so the path is skipped at
`app/pipeline/sanctions.py:217`. **No party match.**

### RRF blend + cross-encoder

`_rrf_blend` (`:126-168`) sums per-path rank contributions; structured
matches get a virtual rank-0 boost so they win ties against pure
semantic hits. Top-10 are reranked by the cross-encoder; the final
output, sorted by `rrf_score`:

```text
source     description                                  similarity  hs_code_overlap     restriction_type
─────────  ───────────────────────────────────────────  ──────────  ─────────────────   ─────────────────
EU_RUSSIA  "Doped chemical elements for electronics"    0.91        ["381800"]          prohibited
BIS_CCL    "Hetero-epitaxial materials (Si/Ge)"         0.84        ["381800","854110"] license_required
EU_RUSSIA  "Electronic integrated circuits"             0.76        ["854231"]          prohibited
BIS_CCL    "Equipment for lithographic processes"       0.73        ["901041"]          license_required
```

## 7. Rules match (stage 6)

`rules.score(...)` (`app/pipeline/rules.py:82`):

- Active rule `id=17` has `destination_iso="RU"` and matches.
- Single phrase `"dual-use semiconductor or lithography equipment"` is
  reranker-scored against the normalized cargo text →
  `phrase_similarity ≈ 0.78`.
- Conditions `{"min_value": 100000, "destination_iso": "RU"}` evaluate
  against shipment context `{value: 480000, currency: USD, ...}`:
  - `shipment_value=480000 >= min_value=100000` ✓
  - `destination_iso` filter applied as a fetch-side predicate at `:96`,
    so we wouldn't have fetched the rule unless it matched.
  - Conditions DSL has no `currency_in` / `metadata_eq` clause →
    `conditions_satisfied = True`.

Output:

```json
[
  {
    "rule_id": 17,
    "rule_name": "High-value dual-use to RU/BY",
    "phrase": "dual-use semiconductor or lithography equipment",
    "phrase_similarity": 0.7800,
    "threshold": 0.65,
    "delta_above_threshold": 0.13,
    "conditions_satisfied": true,
    "version": 1,
    "mode": "single",
    "per_phrase": [{"phrase": "dual-use semiconductor or lithography equipment", "similarity": 0.7800}]
  }
]
```

## 8. Confidence + abstention (stage 7)

`confidence.compute(candidates)` (`app/pipeline/confidence.py:26`):

```python
top1_score              = 0.71
top1_minus_top2         = 0.71 - 0.66 = 0.05
entropy_topk            = 1.94    # spread is moderate
chapter_consensus       = 0.46    # chapter 38 holds ~46% of top-10 mass
cross_source_agreement  = True    # dense, sparse, cross_encoder all > thresholds
```

`compute_abstention(...)` (`:65`):

- `top1_score (0.71) >= top1_threshold (0.45)` — no low-top1 abstention.
- `top1_minus_top2 (0.05) >= gap_threshold (0.05)`, so the ambiguous-chapter
  branch does *not* fire even though chapter consensus is borderline.
- Result: `{"abstained": False, "reason": None, "fallback_level": None}`.

A slightly tighter gap would have flipped this to `ambiguous_chapter`
with a `fallback_level=2` (chapter-only) suggestion. This is the
designed behavior — the engine surfaces the ambiguity instead of
hiding it.

## 9. Assemble + persist (stages 8)

`assemble.build(...)` (`app/pipeline/assemble.py:33`) constructs the
response dict. `versions.build(db, static)`
(`app/pipeline/versions.py:61`) attaches:

```json
{
  "engine":   "0.1.0",
  "embedder": "BAAI/bge-small-en-v1.5",
  "reranker": "BAAI/bge-reranker-v2-m3",
  "ner":      "urchade/gliner_small-v2.1",
  "ltr_path": "./artifacts/ltr.txt",
  "ltr_hash": "sha256:9c0a…",
  "refdata":  {
    "HTS":         "2026-05-12T03:00:00+00:00",
    "OFAC_SDN":    "2026-05-15T03:00:00+00:00",
    "EU_RUSSIA":   "2026-05-16T03:00:00+00:00",
    "BIS_CCL":     "2026-05-16T03:00:00+00:00",
    "ITAR_USML":   "2026-05-10T03:00:00+00:00"
  }
}
```

`routes_screen._persist` (`app/api/routes_screen.py:15-41`) writes a
`Shipment` row + a `ScreeningResult` row that captures the full payload
above.

## 10. Final response

The client receives a `ScreeningResultOut`. Annotated:

```json
{
  "shipment_id": "9e7e5c0a-3f2b-4f3a-9d2e-3a1c4b7f0123",
  "engine_version": "0.1.0",

  "hs_classification": {
    "top_candidates": [
      {
        "hs_code": "381800",
        "level": "subheading",
        "chapter": "38",
        "heading": "3818",
        "title": "Chemical elements doped for use in electronics...",
        "score": 0.71,
        "score_components": {
          "dense": 0.78, "sparse": 0.49, "entity_overlap": 1.00,
          "cross_encoder": 0.86, "chapter_prior": 0.32, "ltr_final": 0.71
        }
      },
      {
        "hs_code": "901041",
        "level": "subheading",
        "chapter": "90",
        "heading": "9010",
        "title": "Photoresists and other materials for use in semiconductor...",
        "score": 0.66,
        "score_components": { "dense": 0.71, "sparse": 0.58, "entity_overlap": 0.65,
                              "cross_encoder": 0.74, "chapter_prior": 0.18, "ltr_final": 0.66 }
      },
      {
        "hs_code": "854231",
        "level": "subheading",
        "chapter": "85",
        "heading": "8542",
        "title": "Electronic integrated circuits — processors and controllers",
        "score": 0.64,
        "score_components": { "dense": 0.73, "sparse": 0.81, "entity_overlap": 0.42,
                              "cross_encoder": 0.61, "chapter_prior": 0.27, "ltr_final": 0.64 }
      }
      // ... up to 10 candidates
    ],

    "chapter_distribution": {"38": 0.46, "85": 0.27, "90": 0.18, "28": 0.06, "39": 0.03},
    "confidence_metrics": {
      "top1_score": 0.71,
      "top1_minus_top2": 0.05,
      "entropy_topk": 1.94,
      "chapter_consensus": 0.46,
      "cross_source_agreement": true
    },
    "abstained": false,
    "abstain_reason": null,
    "fallback_level": null,
    "fallback_candidate": null,
    "multi_commodity": null
  },

  "sanction_matches": [
    {
      "source": "EU_RUSSIA",
      "source_record_id": "ANNEX_VII_28461010",
      "description": "Doped chemical elements for electronics",
      "similarity": 0.9100,
      "country_pair_applicable": true,
      "hs_code_overlap": ["381800"],
      "restriction_type": "prohibited",
      "provenance_url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833",
      "score_components": {
        "dense": 0.74, "sparse": 0.32, "cross_encoder": 0.81,
        "alias_trigram": 0.00, "structured_match": true, "rrf_score": 0.0824
      }
    },
    {
      "source": "BIS_CCL",
      "source_record_id": "ECCN_3C001",
      "description": "Hetero-epitaxial materials (Si/Ge)",
      "similarity": 0.8400,
      "country_pair_applicable": true,
      "hs_code_overlap": ["381800", "854110"],
      "restriction_type": "license_required",
      "score_components": {
        "dense": 0.71, "sparse": 0.18, "cross_encoder": 0.68,
        "alias_trigram": 0.00, "structured_match": true, "rrf_score": 0.0612
      }
    }
    // EU_RUSSIA 854231, BIS_CCL 901041 follow at lower rrf_score
  ],

  "rule_matches": [
    {
      "rule_id": 17,
      "rule_name": "High-value dual-use to RU/BY",
      "phrase": "dual-use semiconductor or lithography equipment",
      "phrase_similarity": 0.7800,
      "threshold": 0.65,
      "delta_above_threshold": 0.13,
      "conditions_satisfied": true,
      "version": 1,
      "mode": "single",
      "per_phrase": [{"phrase": "dual-use semiconductor or lithography equipment", "similarity": 0.7800}]
    }
  ],

  "extracted_entities": {
    "material":    [{"text": "silicon", "start": 0, "end": 7, "score": 0.94}],
    "product":     [{"text": "wafers", "start": 8, "end": 14, "score": 0.91},
                    {"text": "photoresist", "start": 27, "end": 38, "score": 0.86},
                    {"text": "lithography", "start": 107, "end": 118, "score": 0.88}],
    "measurement": [{"text": "300mm", "start": 15, "end": 20, "score": 0.83}],
    "end_use":     [{"text": "semiconductor manufacturing", "start": 50, "end": 76, "score": 0.79}],
    "form":        [{"text": "coating", "start": 39, "end": 46, "score": 0.71}]
  },

  "latency_ms": {
    "ner": 38,
    "retrieval_rerank_fusion": 184,
    "sanctions_rules": 142,
    "assemble": 11,
    "total": 379
  },

  "versions": {
    "engine":   "0.1.0",
    "embedder": "BAAI/bge-small-en-v1.5",
    "reranker": "BAAI/bge-reranker-v2-m3",
    "ner":      "urchade/gliner_small-v2.1",
    "ltr_path": "./artifacts/ltr.txt",
    "ltr_hash": "sha256:9c0a...",
    "refdata":  {"HTS": "2026-05-12T03:00:00+00:00",
                 "EU_RUSSIA": "2026-05-16T03:00:00+00:00",
                 "BIS_CCL":   "2026-05-16T03:00:00+00:00",
                 "OFAC_SDN":  "2026-05-15T03:00:00+00:00"}
  }
}
```

## 11. What the engine has — and hasn't — decided

**Has decided:** the most likely 6-digit HS code (`381800`,
confidence-metrics attached), four applicable sanctions records (two
prohibited EU Russia + two license-required BIS CCL), and one rule
match flagged by value-and-route.

**Has *not* decided:** whether to BLOCK, REVIEW, or CLEAR the shipment.
That is intentional — see the abstention comment at
`app/pipeline/confidence.py:5-8`. The engine surfaces uncertainty
quantitatively; the downstream system (operator UI, broker workflow,
TMS rule engine) decides the disposition. For this example the
operator would almost certainly fail the shipment on the prohibited
EU Russia match alone — but that is policy, not engine output.

## 12. What happens after inference

| Side-effect | Where |
|---|---|
| `Shipment` row written | `app/api/routes_screen.py:17-28` |
| `ScreeningResult` row written with the full payload + version snapshot | `:29-41` |
| Logged event `screen.done` with shipment_id, top1, latency, counts | `app/pipeline/orchestrator.py:179-191` |
| Future feedback (operator corrects HS code, marks false positive, etc.) | `FeedbackEvent` row keyed to `result_id` (`app/db/models.py:196-205`) |
| Reproducibility | `screening_result.versions` lets us re-run the pipeline against the same refdata snapshot and the same LTR booster if needed for audit |
