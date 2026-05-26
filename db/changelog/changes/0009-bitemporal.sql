--liquibase formatted sql

-- Phase 1 schema foundation (items 6, 7, 8, 11).
--
-- Makes `sanctioned_commodity` bitemporal so any past decision can be replayed
-- against the exact list contents that were live at the time. Design choice:
-- separate (valid_from, valid_to) + (sys_from, sys_to) timestamp columns rather
-- than two `tstzrange` columns. The temporal EXCLUDE constraint is built from
-- `tstzrange(...)` expressions (identical semantics), while the hot-path
-- "current version" filter stays a trivial `sys_to IS NULL` — cheap in SQL and
-- clean in the ORM. NULL upper bound == open/infinity.
--
-- country_rule / aliases stay current-snapshot (commodity-only bitemporal, per
-- design decision): the ingester regenerates them against the live version.

--changeset screening:0009-btree-gist
CREATE EXTENSION IF NOT EXISTS btree_gist;
--rollback DROP EXTENSION IF EXISTS btree_gist;

--changeset screening:0009-embedding-generation
-- Item 1 foundation: records which embedding model/column is authoritative per table.
CREATE TABLE embedding_generation (
    table_name     text        PRIMARY KEY,
    active_column  text        NOT NULL DEFAULT 'embedding',
    active_model   text        NOT NULL,
    effective_from timestamptz NOT NULL DEFAULT now()
);
INSERT INTO embedding_generation (table_name, active_column, active_model)
VALUES ('sanctioned_commodity', 'embedding', 'BAAI/bge-small-en-v1.5');
--rollback DROP TABLE IF EXISTS embedding_generation;

--changeset screening:0009-commodity-id-seq
CREATE SEQUENCE IF NOT EXISTS sanctioned_commodity_commodity_id_seq;
--rollback DROP SEQUENCE IF EXISTS sanctioned_commodity_commodity_id_seq;

--changeset screening:0009-bitemporal-columns
ALTER TABLE sanctioned_commodity
    ADD COLUMN commodity_id    bigint,
    ADD COLUMN content_hash    bytea,
    ADD COLUMN embedding_model text,
    ADD COLUMN program_tag     text,
    ADD COLUMN valid_from      timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN valid_to        timestamptz,
    ADD COLUMN sys_from        timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN sys_to          timestamptz;
-- Backfill: existing rows are each their own logical commodity (commodity_id = id),
-- their vectors are from the original encoder, and they are the current version.
UPDATE sanctioned_commodity SET commodity_id = id WHERE commodity_id IS NULL;
UPDATE sanctioned_commodity
   SET embedding_model = 'BAAI/bge-small-en-v1.5'
 WHERE embedding_model IS NULL AND embedding IS NOT NULL;
SELECT setval('sanctioned_commodity_commodity_id_seq',
              GREATEST((SELECT COALESCE(max(commodity_id), 1) FROM sanctioned_commodity), 1));
ALTER TABLE sanctioned_commodity ALTER COLUMN commodity_id SET NOT NULL;
ALTER TABLE sanctioned_commodity
    ALTER COLUMN commodity_id SET DEFAULT nextval('sanctioned_commodity_commodity_id_seq');
--rollback ALTER TABLE sanctioned_commodity DROP COLUMN commodity_id, DROP COLUMN content_hash, DROP COLUMN embedding_model, DROP COLUMN program_tag, DROP COLUMN valid_from, DROP COLUMN valid_to, DROP COLUMN sys_from, DROP COLUMN sys_to;

--changeset screening:0009-bitemporal-exclude
-- No two row-versions of the same logical commodity may overlap in both
-- application-time and system-time. Requires btree_gist for the `=` on bigint.
ALTER TABLE sanctioned_commodity
    ADD CONSTRAINT sanctioned_commodity_bitemporal_excl
    EXCLUDE USING gist (
        commodity_id WITH =,
        tstzrange(valid_from, valid_to) WITH &&,
        tstzrange(sys_from, sys_to) WITH &&
    );
--rollback ALTER TABLE sanctioned_commodity DROP CONSTRAINT IF EXISTS sanctioned_commodity_bitemporal_excl;

--changeset screening:0009-current-unique
-- Item 11: exactly one *current* version per (source, source_record_id). NULLS NOT
-- DISTINCT so two current rows with NULL source_record_id from the same source can't
-- both exist. The old plain UNIQUE(source, source_record_id) is wrong under versioning
-- (historical versions legitimately share the key) and is replaced by this partial index.
ALTER TABLE sanctioned_commodity DROP CONSTRAINT IF EXISTS uq_sanctioned_commodity_source_recid;
CREATE UNIQUE INDEX uq_sanctioned_commodity_current
    ON sanctioned_commodity (source, source_record_id) NULLS NOT DISTINCT
    WHERE sys_to IS NULL;
--rollback DROP INDEX IF EXISTS uq_sanctioned_commodity_current; ALTER TABLE sanctioned_commodity ADD CONSTRAINT uq_sanctioned_commodity_source_recid UNIQUE (source, source_record_id);

--changeset screening:0009-tsv-generated
-- Item 8: description_tsv becomes a generated stored column so it can never drift
-- from description. 'simple' (not 'english') — commodity/dual-use descriptions are
-- multilingual and benefit from unstemmed exact matching.
DROP INDEX IF EXISTS sanctioned_commodity_tsv_gin;
ALTER TABLE sanctioned_commodity DROP COLUMN description_tsv;
ALTER TABLE sanctioned_commodity
    ADD COLUMN description_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(description, ''))) STORED;
CREATE INDEX sanctioned_commodity_tsv_gin ON sanctioned_commodity USING gin (description_tsv);
--rollback DROP INDEX IF EXISTS sanctioned_commodity_tsv_gin; ALTER TABLE sanctioned_commodity DROP COLUMN description_tsv; ALTER TABLE sanctioned_commodity ADD COLUMN description_tsv tsvector; CREATE INDEX sanctioned_commodity_tsv_gin ON sanctioned_commodity USING gin (description_tsv);

--changeset screening:0009-current-hnsw
-- Hot path screens only current versions, so the ANN graph covers just those rows.
DROP INDEX IF EXISTS sanctioned_commodity_embedding_hnsw;
CREATE INDEX sanctioned_commodity_embedding_hnsw_current
    ON sanctioned_commodity USING hnsw (embedding vector_cosine_ops)
    WHERE sys_to IS NULL;
--rollback DROP INDEX IF EXISTS sanctioned_commodity_embedding_hnsw_current; CREATE INDEX sanctioned_commodity_embedding_hnsw ON sanctioned_commodity USING hnsw (embedding vector_cosine_ops);
