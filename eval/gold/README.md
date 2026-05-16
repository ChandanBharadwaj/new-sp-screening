# Gold dataset

**Real-data only.** The repo does not ship hand-written gold rows.

The splits at `eval/gold/splits/{train,dev,test}.jsonl` are produced from already-ingested rows.

To create them:
1. Open the **Admin** page in the UI.
2. Run **HTS** (auto-download).
3. Run **CROSS** (auto-scrape + ingest; bound `max_rulings` from the params form if you want a smaller first cut).
4. Optionally upload a Census Schedule B CSV via the **ScheduleB** card and click Run.
5. Run **GoldAssembly** — stratifies by 2-digit chapter and writes the three splits with 70/15/15 ratios.

Run history surfaces on the Status and Data pages as `source=GoldAssembly`.
