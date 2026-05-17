--liquibase formatted sql

--changeset screening:0002-training-run
CREATE TABLE training_run (
    id                bigserial    PRIMARY KEY,
    kind              varchar(32)  NOT NULL,
    started_at        timestamptz  DEFAULT now(),
    finished_at       timestamptz,
    status            varchar(16)  DEFAULT 'running',
    error_message     text,
    params            jsonb,
    artifact_path     text,
    dataset_csv_path  text,
    metrics           jsonb
);
--rollback DROP TABLE IF EXISTS training_run CASCADE;

--changeset screening:0002-eval-job
CREATE TABLE eval_job (
    id             bigserial    PRIMARY KEY,
    started_at     timestamptz  DEFAULT now(),
    finished_at    timestamptz,
    status         varchar(16)  DEFAULT 'running',
    error_message  text,
    classifier     varchar(64)  NOT NULL,
    split          varchar(16)  NOT NULL,
    limit_n        integer,
    eval_run_id    bigint       REFERENCES eval_run(id)
);
--rollback DROP TABLE IF EXISTS eval_job CASCADE;

--changeset screening:0002-job-log
CREATE TABLE job_log (
    id         bigserial    PRIMARY KEY,
    run_table  varchar(32)  NOT NULL,
    run_id     bigint       NOT NULL,
    ts         timestamptz  DEFAULT now(),
    level      varchar(8)   DEFAULT 'info',
    line       text         NOT NULL
);
--rollback DROP TABLE IF EXISTS job_log CASCADE;

--changeset screening:0002-idx-job-log-run-id
CREATE INDEX job_log_run_id_idx ON job_log (run_table, run_id, id);
--rollback DROP INDEX IF EXISTS job_log_run_id_idx;

--changeset screening:0002-threshold
CREATE TABLE threshold (
    key         varchar(64)        PRIMARY KEY,
    value       double precision   NOT NULL,
    updated_at  timestamptz        DEFAULT now(),
    source      varchar(16)        DEFAULT 'ui'
);
--rollback DROP TABLE IF EXISTS threshold CASCADE;

--changeset screening:0002-idx-training-run-started
CREATE INDEX training_run_started ON training_run (started_at DESC);
--rollback DROP INDEX IF EXISTS training_run_started;

--changeset screening:0002-idx-eval-job-started
CREATE INDEX eval_job_started ON eval_job (started_at DESC);
--rollback DROP INDEX IF EXISTS eval_job_started;
