--liquibase formatted sql

-- Item 1 (embedder↔stored-vector contract versioning), scoped to sanctioned_commodity.
--
-- Adds a second-generation vector column so the embedder can be swapped without silent
-- recall loss: backfill embedding_v2 with the new model, run the parity gate, then flip
-- embedding_generation.active_column to 'embedding_v2' in a single transaction. The
-- retrieval dense path reads the active column name from embedding_generation; each
-- generation has its own partial HNSW graph. embedding_generation already carries the
-- sanctioned_commodity row (active_column='embedding') from migration 0009.

--changeset screening:0011-embedding-v2-column
ALTER TABLE sanctioned_commodity ADD COLUMN embedding_v2 vector(384);
ALTER TABLE sanctioned_commodity ADD COLUMN embedding_v2_model text;
--rollback ALTER TABLE sanctioned_commodity DROP COLUMN IF EXISTS embedding_v2, DROP COLUMN IF EXISTS embedding_v2_model;

--changeset screening:0011-embedding-v2-hnsw
CREATE INDEX sanctioned_commodity_embedding_v2_hnsw_current
    ON sanctioned_commodity USING hnsw (embedding_v2 vector_cosine_ops)
    WHERE embedding_v2 IS NOT NULL AND sys_to IS NULL;
--rollback DROP INDEX IF EXISTS sanctioned_commodity_embedding_v2_hnsw_current;
