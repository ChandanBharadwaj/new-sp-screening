# Gold dataset

Phase 0 stub set — small to keep the repo light. Expand to ≥1000 pairs (README §14) before relying on numbers.

Schema (JSONL):
```
{"description": "...", "hs_code": "6-digit code", "ruling_id": "optional source id"}
```

Files:
- `cross_curated.jsonl` — analyst-curated CROSS subset; consumed by `app.refdata.cross.ingest` to seed `hs_training_example`.
- `splits/{train,dev,test}.jsonl` — stratified by chapter. Used by `eval.runners.run_eval` and `app.training.ltr_dataset`.

Build a real 1000-pair set by:
1. Running `app.refdata.cross.scraper` to pull HTML.
2. Running `app.refdata.cross.ingest` against `--html-dir data/cross_raw` to populate training examples.
3. Sampling a stratified-by-chapter subset back out into `splits/` (script TBD; trivial pandas one-liner).
