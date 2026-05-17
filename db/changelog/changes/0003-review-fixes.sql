--liquibase formatted sql

--changeset screening:0003-screening-result-versions
ALTER TABLE screening_result ADD COLUMN versions jsonb;
--rollback ALTER TABLE screening_result DROP COLUMN versions;

--changeset screening:0003-screening-rule-phrase-group
ALTER TABLE screening_rule ADD COLUMN phrase_group jsonb;
--rollback ALTER TABLE screening_rule DROP COLUMN phrase_group;

--changeset screening:0003-sanctioned-commodity-alias
CREATE TABLE sanctioned_commodity_alias (
    id                       bigserial   PRIMARY KEY,
    sanctioned_commodity_id  bigint      NOT NULL REFERENCES sanctioned_commodity(id) ON DELETE CASCADE,
    alias                    text        NOT NULL,
    alias_kind               varchar(16),
    created_at               timestamptz DEFAULT now(),
    CONSTRAINT uq_alias_per_commodity UNIQUE (sanctioned_commodity_id, alias)
);
--rollback DROP TABLE IF EXISTS sanctioned_commodity_alias CASCADE;

--changeset screening:0003-idx-alias-sanctioned-commodity-id
CREATE INDEX ix_alias_sanctioned_commodity_id ON sanctioned_commodity_alias (sanctioned_commodity_id);
--rollback DROP INDEX IF EXISTS ix_alias_sanctioned_commodity_id;

--changeset screening:0003-idx-alias-trgm
CREATE INDEX ix_alias_alias_trgm ON sanctioned_commodity_alias USING gin (alias gin_trgm_ops);
--rollback DROP INDEX IF EXISTS ix_alias_alias_trgm;
