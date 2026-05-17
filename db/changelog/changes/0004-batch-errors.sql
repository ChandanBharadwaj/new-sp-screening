--liquibase formatted sql

-- BatchJob.failed_rows is a count only — when a CSV upload fails partway, operators
-- see "N failed" and have no way to fix the bad rows. This adds a per-row error
-- table the worker writes to when a screen attempt raises.

--changeset screening:0004-batch-job-error
CREATE TABLE batch_job_error (
    id             bigserial    PRIMARY KEY,
    batch_id       uuid         NOT NULL REFERENCES batch_job(id) ON DELETE CASCADE,
    row_index      integer      NOT NULL,
    raw_row        jsonb,
    error_message  text         NOT NULL,
    created_at     timestamptz  DEFAULT now()
);
--rollback DROP TABLE IF EXISTS batch_job_error CASCADE;

--changeset screening:0004-idx-batch-job-error-batch
CREATE INDEX ix_batch_job_error_batch ON batch_job_error (batch_id, row_index);
--rollback DROP INDEX IF EXISTS ix_batch_job_error_batch;
