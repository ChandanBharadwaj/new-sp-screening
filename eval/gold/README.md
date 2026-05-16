# Gold dataset

**Real-data only.** The repo does not ship hand-written gold rows under the no-mock-data policy.

The splits at `eval/gold/splits/{train,dev,test}.jsonl` are produced by sampling already-ingested rows from `hs_training_example` via:

```bash
python -m app.refdata.gold.assemble --target 1200 --per-chapter 30
```

Prerequisites:
1. `python -m app.refdata.hts.ingest --year 2025`
2. `python -m app.refdata.cross.scraper --max-rulings 5000`
3. `python -m app.refdata.cross.ingest --html-dir data/cross_raw/rulings`
4. (Optional) `python -m app.refdata.schedule_b.ingest --file ./data/schedule_b/schedule_b.csv`

The assemble script stratifies by 2-digit chapter and splits 70/15/15 by chapter to avoid leakage. Run history surfaces on the Status UI as `source=GoldAssembly`.
