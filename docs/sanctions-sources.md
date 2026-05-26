# Sanctions source provenance

All sources listed below are imported from authoritative publishers; no synthetic / generated data is loaded.

This is a **commodity** screening engine. Party / entity screening (designated
persons, vessels, aircraft) is explicitly **out of scope** and handled by a
separate dedicated party-screening system — so only commodity-focused sources
are ingested below.

## In scope — commodity sources

| Source | Provenance | Format | HS coverage | Ingester |
|---|---|---|---|---|
| EU Dual-Use Annex I (Council Reg 2021/821) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02021R0821 | XLSX/PDF + EU CN crosswalk XLSX | EU dual-use category codes; HS via crosswalk where available | `app.refdata.sanctions.eu_dual_use.ingest` |
| EU Russia annexes (Council Reg 833/2014) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833 | XLSX/PDF per annex | CN/HS codes inline | `app.refdata.sanctions.eu_russia.ingest` |
| US BIS Commerce Control List (15 CFR Part 774 Supp. 1) | https://www.bis.doc.gov/index.php/regulations/commerce-control-list-ccl | CSV/XLSX text export | ECCN; HS via BIS HS-ECCN crosswalk | `app.refdata.sanctions.bis_ccl.ingest` |
| US ITAR / USML (22 CFR Part 121) | https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M/part-121 | CSV/XLSX (operator-supplied) | USML category; HS optional per row | `app.refdata.sanctions.itar.ingest` |
| Country-program commodity restrictions (Iran, DPRK, Syria, Cuba, Venezuela) | 31 CFR Chapter V parts | curated YAML | HS prefixes expanded at ingest | `app.refdata.sanctions.country_program.ingest` |
| Operator keyword lists | operator-authored | CSV | semantic-only (HS empty) | `app.refdata.keyword_lists.ingest` |

## Out of scope — party / entity lists (handled by the separate party-screening system)

| Source | Why excluded here |
|---|---|
| OFAC SDN, OFAC Consolidated (non-SDN) | Entity/person lists, not commodities — no goods records to populate `sanctioned_commodity` |
| UN Consolidated Sanctions List | Designated persons/entities |
| EU Consolidated Financial Sanctions (FSF) | Designated persons/entities |
| BIS Denied Persons / Entity List (party portions), UK HMT/OFSI | Party designations |

The ingesters for these party lists were intentionally removed; the API gateway
calls both this engine and the party-screening system and combines decisions
(either side raising a hit triggers review).

## Operator workflow

1. Visit each publisher URL above and download the relevant file(s) into `./data/sanctions/`.
2. Run the corresponding `python -m app.refdata.sanctions.<source>.ingest --file ...` CLI; each writes a `refdata_run` row and surfaces on the Status UI.
3. Re-run any source by re-downloading and re-issuing the CLI — ingest is idempotent on `(source, source_record_id)`.
