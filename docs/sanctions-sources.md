# Sanctions source provenance

All sources listed below are imported from authoritative publishers; no synthetic / generated data is loaded.

## In scope (Phase 2)

| Source | Provenance | Format | HS coverage | Ingester |
|---|---|---|---|---|
| EU Dual-Use Annex I (Council Reg 2021/821) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02021R0821 | XLSX/PDF + EU CN crosswalk XLSX | EU dual-use category codes; HS via crosswalk where available | `app.refdata.sanctions.eu_dual_use.ingest` |
| EU Russia annexes (Council Reg 833/2014) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833 | XLSX/PDF per annex | CN/HS codes inline | `app.refdata.sanctions.eu_russia.ingest` |
| US BIS Commerce Control List (15 CFR Part 774 Supp. 1) | https://www.bis.doc.gov/index.php/regulations/commerce-control-list-ccl | CSV/XLSX text export | ECCN; HS via BIS HS-ECCN crosswalk | `app.refdata.sanctions.bis_ccl.ingest` |
| UN Consolidated Sanctions List | https://main.un.org/securitycouncil/en/sanctions/un-sc-consolidated-list | XML (https://scsanctions.un.org/resources/xml/en/consolidated.xml) | None inline; HS left empty, semantic matching only | `app.refdata.sanctions.un.ingest` |
| EU Consolidated Financial Sanctions (FSF) | https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/ | XML (requires registered token) | None inline; HS left empty | `app.refdata.sanctions.eu_consolidated.ingest` |

## Skipped (would require synthesized HS mappings — out of scope under the no-generated-data rule)

| Source | Reason for skip |
|---|---|
| OFAC SDN | Entity-only list; no goods records that would populate `sanctioned_commodity` |
| OFAC sectoral | Narrative restrictions; analysts would have to map regimes to HS codes |
| US ITAR / USML | Published as PDF prose under 22 CFR Part 121; no machine-readable HS crosswalk |
| Country-specific narrative regimes (Iran, DPRK, Syria, Cuba, Venezuela) beyond what EU/US publish as HS-coded annexes | Mapping requires analyst hand-labelling |

These can be revisited once an internal analyst process produces HS mappings from the regulations; those mappings would then themselves be the imported data.

## Operator workflow

1. Visit each publisher URL above and download the relevant file(s) into `./data/sanctions/`.
2. Run the corresponding `python -m app.refdata.sanctions.<source>.ingest --file ...` CLI; each writes a `refdata_run` row and surfaces on the Status UI.
3. Re-run any source by re-downloading and re-issuing the CLI — ingest is idempotent on `(source, source_record_id)`.
