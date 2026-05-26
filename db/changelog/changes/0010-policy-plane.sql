--liquibase formatted sql

-- Phase 2 policy plane (items 4, 10).
--
-- Moves screening policy out of Python constants into effective-dated Postgres
-- tables so every value bound to a decision is auditable ("on 2026-03-14 the
-- GLiNER threshold was 0.40, approved by X in CR-1421"). Two tables:
--   inference_threshold — numeric decision thresholds (hs_classify abstention).
--   policy_parameter    — everything else (jsonb values: scores, weights, limits).
-- Both are effective-dated with a btree_gist EXCLUDE so no two active rows for the
-- same key overlap in time. Seeded from the current code defaults.

--changeset screening:0010-inference-threshold
CREATE TABLE inference_threshold (
    threshold_id    bigserial   PRIMARY KEY,
    pipeline        text        NOT NULL,           -- 'hs_classify'
    parameter       text        NOT NULL,           -- 'min_top1','min_gap','min_chapter_consensus'
    value           numeric     NOT NULL,
    calibrated_from text        NOT NULL DEFAULT 'code_default',  -- mlflow run id once calibrated
    effective_from  timestamptz NOT NULL DEFAULT now(),
    effective_to    timestamptz,
    created_by      text        NOT NULL DEFAULT 'system',
    approved_by     text        NOT NULL DEFAULT 'bootstrap',
    rationale       text        NOT NULL DEFAULT 'seed from code defaults',
    EXCLUDE USING gist (
        pipeline WITH =, parameter WITH =,
        tstzrange(effective_from, effective_to) WITH &&
    )
);
INSERT INTO inference_threshold (pipeline, parameter, value) VALUES
    ('hs_classify', 'min_top1',             0.45),
    ('hs_classify', 'min_gap',              0.05),
    ('hs_classify', 'min_chapter_consensus',0.40);
--rollback DROP TABLE IF EXISTS inference_threshold;

--changeset screening:0010-policy-parameter
CREATE TABLE policy_parameter (
    param_id        bigserial   PRIMARY KEY,
    scope           text        NOT NULL,           -- 'gliner','alias_match','decompose','ltr'
    name            text        NOT NULL,           -- 'min_score','min_similarity','conf_gate','fallback_weights'
    value           jsonb       NOT NULL,
    effective_from  timestamptz NOT NULL DEFAULT now(),
    effective_to    timestamptz,
    created_by      text        NOT NULL DEFAULT 'system',
    approved_by     text        NOT NULL DEFAULT 'bootstrap',
    change_ticket   text        NOT NULL DEFAULT 'BOOTSTRAP',
    rationale       text        NOT NULL DEFAULT 'initial seed from code defaults',
    canary_pct      int         NOT NULL DEFAULT 100 CHECK (canary_pct BETWEEN 0 AND 100),
    CHECK (created_by <> approved_by),
    EXCLUDE USING gist (
        scope WITH =, name WITH =,
        tstzrange(effective_from, effective_to) WITH &&
    )
);
INSERT INTO policy_parameter (scope, name, value) VALUES
    ('gliner',      'min_score',        '0.4'),
    ('alias_match', 'min_similarity',   '0.45'),
    ('decompose',   'conf_gate',        '0.5'),
    ('ltr',         'fallback_weights', '[0.20,0.10,0.15,0.45,0.05,0.0,0.05]');
--rollback DROP TABLE IF EXISTS policy_parameter;
