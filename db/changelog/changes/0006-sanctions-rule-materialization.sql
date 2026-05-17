--liquibase formatted sql

-- Materialize ScreeningRule rows from sanction-source commodity data.
--
-- The country-program + OFAC/EU/BIS/ITAR/UN ingesters populate `sanctioned_commodity`
-- and `country_rule` today, but those rows never flow into `screening_rule`, so the
-- cross-encoder rule path (app/pipeline/rules.py) can only score operator-authored
-- phrases. This changeset adds:
--
--   1. `sanctions_rule_config`: per-source on/off + threshold + phrase-split strategy,
--      so the operator controls materialization from the Admin UI (no YAML edits).
--
--   2. A partial unique index on `screening_rule (created_by, name)` scoped to
--      materialized rows only. That gives the materializer an UPSERT target while
--      leaving operator-authored rules' versioning model (insert new row with
--      same name + version+1; see app/api/routes_rules.py::update_rule) untouched.

--changeset screening:0006-sanctions-rule-config
CREATE TABLE sanctions_rule_config (
    source              text         PRIMARY KEY,
    enabled             boolean      NOT NULL DEFAULT false,
    default_threshold   real         NOT NULL DEFAULT 0.55,
    phrase_strategy     text         NOT NULL DEFAULT 'split_lists',
    updated_at          timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT ck_sanctions_rule_config_threshold
        CHECK (default_threshold >= 0.0 AND default_threshold <= 1.0),
    CONSTRAINT ck_sanctions_rule_config_strategy
        CHECK (phrase_strategy IN ('description_only', 'with_aliases', 'split_lists'))
);
--rollback DROP TABLE IF EXISTS sanctions_rule_config;

--changeset screening:0006-uq-screening-rule-materialized
-- Partial unique: only materialized rows participate. Operator-authored rules
-- (created_by NULL or a non-'sanctions_source:' value) are excluded, so the
-- existing same-name/different-version pattern in routes_rules.py keeps working.
CREATE UNIQUE INDEX uq_screening_rule_materialized
    ON screening_rule (created_by, name)
    WHERE created_by LIKE 'sanctions_source:%';
--rollback DROP INDEX IF EXISTS uq_screening_rule_materialized;
