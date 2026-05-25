--liquibase formatted sql

-- Operator-authored keyword lists as a sanctions data source.
--
-- A keyword list (e.g. "seafood") is an analyst-curated CSV of words/phrases that
-- are sanctioned in some context (a category like seafood, dual-use chemicals,
-- luxury goods, etc.). Per the unified data-layer design, each keyword becomes a
-- `sanctioned_commodity` row under `source = 'KW:<list_name>'`; companion
-- `country_rule` rows carry the list's origin/destination scope; the existing
-- `materialize_rules.materialize_for_source` then derives one `screening_rule`
-- per keyword so the cross-encoder evaluates it at screen time. No new scoring
-- code path is introduced — the keyword-list content rides on the same
-- `sanctioned_commodity` + `country_rule` + `screening_rule` machinery used for
-- OFAC, EU, BIS, ITAR, UN, and the country-program YAMLs.
--
-- This changeset adds the *manifest* table only: per-list metadata (label,
-- scope, threshold, source file path, active flag, last ingest timestamp,
-- current row count). Content lives in `sanctioned_commodity` like every other
-- source.

--changeset screening:0007-keyword-list
CREATE TABLE keyword_list (
    name               text         PRIMARY KEY,
    label              text,
    origin_iso         char(2),
    destination_iso    char(2),
    direction          text,
    restriction_type   text         NOT NULL DEFAULT 'watchlist',
    default_threshold  real         NOT NULL DEFAULT 0.55,
    active             boolean      NOT NULL DEFAULT true,
    source_file        text,
    row_count          integer      NOT NULL DEFAULT 0,
    last_ingested_at   timestamptz,
    updated_at         timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ck_keyword_list_threshold
        CHECK (default_threshold >= 0.0 AND default_threshold <= 1.0),
    CONSTRAINT ck_keyword_list_direction
        CHECK (direction IS NULL OR direction IN ('import_from', 'export_to', 'both'))
);
--rollback DROP TABLE IF EXISTS keyword_list;
