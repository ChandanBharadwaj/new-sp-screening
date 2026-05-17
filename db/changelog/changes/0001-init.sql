--liquibase formatted sql

--changeset screening:0001-init-extensions
--comment: pgvector for embeddings, pg_trgm for fuzzy alias lookup, pgcrypto for gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
--rollback DROP EXTENSION IF EXISTS "pgcrypto"; DROP EXTENSION IF EXISTS pg_trgm; DROP EXTENSION IF EXISTS vector;

--changeset screening:0001-init-hs-code
CREATE TABLE hs_code (
    code             varchar(10)  PRIMARY KEY,
    level            smallint     NOT NULL,
    parent_code      varchar(10)  REFERENCES hs_code(code),
    chapter          varchar(2)   NOT NULL,
    title            text         NOT NULL,
    description      text,
    chapter_notes    text,
    section_notes    text,
    embedding        vector(384),
    description_tsv  tsvector,
    created_at       timestamptz  DEFAULT now(),
    updated_at       timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS hs_code CASCADE;

--changeset screening:0001-init-hs-entity-index
CREATE TABLE hs_entity_index (
    hs_code       varchar(10) REFERENCES hs_code(code),
    entity_type   varchar(32),
    entity_value  text,
    weight        real,
    PRIMARY KEY (hs_code, entity_type, entity_value)
);
--rollback DROP TABLE IF EXISTS hs_entity_index CASCADE;

--changeset screening:0001-init-hs-training-example
CREATE TABLE hs_training_example (
    id               bigserial    PRIMARY KEY,
    source           varchar(32)  NOT NULL,
    source_id        text,
    description      text         NOT NULL,
    hs_code          varchar(10)  REFERENCES hs_code(code),
    embedding        vector(384),
    description_tsv  tsvector,
    created_at       timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS hs_training_example CASCADE;

--changeset screening:0001-init-sanctioned-commodity
CREATE TABLE sanctioned_commodity (
    id                bigserial    PRIMARY KEY,
    source            varchar(32)  NOT NULL,
    source_record_id  text,
    description       text         NOT NULL,
    hs_codes          varchar(10)[],
    restriction_type  varchar(32),
    effective_from    date,
    effective_to      date,
    provenance_url    text,
    embedding         vector(384),
    description_tsv   tsvector,
    created_at        timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS sanctioned_commodity CASCADE;

--changeset screening:0001-init-country-rule
CREATE TABLE country_rule (
    id                       bigserial    PRIMARY KEY,
    origin_iso               char(2),
    destination_iso          char(2),
    sanctioned_commodity_id  bigint       REFERENCES sanctioned_commodity(id),
    restriction_type         varchar(32),
    conditions               jsonb,
    active                   boolean      DEFAULT true,
    created_at               timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS country_rule CASCADE;

--changeset screening:0001-init-screening-rule
CREATE TABLE screening_rule (
    id                bigserial    PRIMARY KEY,
    name              text         NOT NULL,
    phrase            text         NOT NULL,
    embedding         vector(384),
    threshold         real         NOT NULL,
    conditions        jsonb,
    origin_iso        char(2),
    destination_iso   char(2),
    active            boolean      DEFAULT true,
    version           integer      DEFAULT 1,
    created_by        text,
    created_at        timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS screening_rule CASCADE;

--changeset screening:0001-init-shipment
CREATE TABLE shipment (
    id               uuid           PRIMARY KEY DEFAULT gen_random_uuid(),
    external_ref     text,
    commodity_text   text           NOT NULL,
    cargo_text       text,
    origin_iso       char(2),
    destination_iso  char(2),
    shipment_value   numeric(18,2),
    currency         char(3),
    metadata         jsonb,
    created_at       timestamptz    DEFAULT now()
);
--rollback DROP TABLE IF EXISTS shipment CASCADE;

--changeset screening:0001-init-screening-result
CREATE TABLE screening_result (
    id                   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id          uuid         REFERENCES shipment(id),
    hs_candidates        jsonb,
    sanction_matches     jsonb,
    rule_matches         jsonb,
    extracted_entities   jsonb,
    confidence_metrics   jsonb,
    latency_ms           jsonb,
    engine_version       text,
    created_at           timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS screening_result CASCADE;

--changeset screening:0001-init-feedback-event
CREATE TABLE feedback_event (
    id            bigserial    PRIMARY KEY,
    result_id     uuid         REFERENCES screening_result(id),
    analyst_id    text,
    event_type    varchar(32),
    before_value  jsonb,
    after_value   jsonb,
    notes         text,
    created_at    timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS feedback_event CASCADE;

--changeset screening:0001-init-refdata-run
CREATE TABLE refdata_run (
    id             bigserial    PRIMARY KEY,
    source         varchar(32)  NOT NULL,
    started_at     timestamptz  DEFAULT now(),
    finished_at    timestamptz,
    rows_upserted  integer      DEFAULT 0,
    status         varchar(16)  DEFAULT 'running',
    error_message  text,
    notes          text
);
--rollback DROP TABLE IF EXISTS refdata_run CASCADE;

--changeset screening:0001-init-eval-run
CREATE TABLE eval_run (
    id               bigserial    PRIMARY KEY,
    ran_at           timestamptz  DEFAULT now(),
    classifier       varchar(64)  NOT NULL,
    split            varchar(16)  NOT NULL,
    top1_subheading  double precision,
    top3_subheading  double precision,
    top1_chapter     double precision,
    mrr              double precision,
    p50_ms           double precision,
    p95_ms           double precision,
    p99_ms           double precision,
    n_examples       integer,
    report_json      jsonb
);
--rollback DROP TABLE IF EXISTS eval_run CASCADE;

--changeset screening:0001-init-batch-job
CREATE TABLE batch_job (
    id              uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    filename        text,
    total_rows      integer      DEFAULT 0,
    completed_rows  integer      DEFAULT 0,
    failed_rows     integer      DEFAULT 0,
    status          varchar(16)  DEFAULT 'pending',
    created_at      timestamptz  DEFAULT now(),
    updated_at      timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS batch_job CASCADE;

--changeset screening:0001-idx-hs-code-embedding-hnsw
CREATE INDEX hs_code_embedding_hnsw ON hs_code USING hnsw (embedding vector_cosine_ops);
--rollback DROP INDEX IF EXISTS hs_code_embedding_hnsw;

--changeset screening:0001-idx-hs-code-tsv-gin
CREATE INDEX hs_code_tsv_gin ON hs_code USING gin (description_tsv);
--rollback DROP INDEX IF EXISTS hs_code_tsv_gin;

--changeset screening:0001-idx-hs-training-example-embedding-hnsw
CREATE INDEX hs_training_example_embedding_hnsw ON hs_training_example USING hnsw (embedding vector_cosine_ops);
--rollback DROP INDEX IF EXISTS hs_training_example_embedding_hnsw;

--changeset screening:0001-idx-hs-training-example-tsv-gin
CREATE INDEX hs_training_example_tsv_gin ON hs_training_example USING gin (description_tsv);
--rollback DROP INDEX IF EXISTS hs_training_example_tsv_gin;

--changeset screening:0001-idx-sanctioned-commodity-embedding-hnsw
CREATE INDEX sanctioned_commodity_embedding_hnsw ON sanctioned_commodity USING hnsw (embedding vector_cosine_ops);
--rollback DROP INDEX IF EXISTS sanctioned_commodity_embedding_hnsw;

--changeset screening:0001-idx-sanctioned-commodity-tsv-gin
CREATE INDEX sanctioned_commodity_tsv_gin ON sanctioned_commodity USING gin (description_tsv);
--rollback DROP INDEX IF EXISTS sanctioned_commodity_tsv_gin;

--changeset screening:0001-idx-screening-rule-embedding-hnsw
CREATE INDEX screening_rule_embedding_hnsw ON screening_rule USING hnsw (embedding vector_cosine_ops);
--rollback DROP INDEX IF EXISTS screening_rule_embedding_hnsw;

--changeset screening:0001-idx-refdata-run-source-started
CREATE INDEX refdata_run_source_started ON refdata_run (source, started_at DESC);
--rollback DROP INDEX IF EXISTS refdata_run_source_started;

--changeset screening:0001-idx-eval-run-classifier-split-ran
CREATE INDEX eval_run_classifier_split_ran ON eval_run (classifier, split, ran_at DESC);
--rollback DROP INDEX IF EXISTS eval_run_classifier_split_ran;

--changeset screening:0001-idx-hs-code-chapter
CREATE INDEX hs_code_chapter ON hs_code (chapter);
--rollback DROP INDEX IF EXISTS hs_code_chapter;

--changeset screening:0001-idx-hs-code-level
CREATE INDEX hs_code_level ON hs_code (level);
--rollback DROP INDEX IF EXISTS hs_code_level;

--changeset screening:0001-idx-hs-training-example-source
CREATE INDEX hs_training_example_source ON hs_training_example (source);
--rollback DROP INDEX IF EXISTS hs_training_example_source;

--changeset screening:0001-idx-screening-result-shipment
CREATE INDEX screening_result_shipment ON screening_result (shipment_id);
--rollback DROP INDEX IF EXISTS screening_result_shipment;
