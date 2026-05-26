--liquibase formatted sql

-- Item 9 (boundary ISO discipline): country codes are validated + upper-cased at the
-- FastAPI boundary (CountryAlpha2 in app/schemas). These CHECK constraints are the
-- belt-and-braces safety net for any write path that bypasses pydantic (e.g. direct
-- ingest / batch loads), so a stored `ir` can never silently miss the case-sensitive
-- country_rule join in app/pipeline/sanctions.py. NULL stays allowed (route-agnostic rules).

--changeset screening:0008-chk-shipment-iso
ALTER TABLE shipment
    ADD CONSTRAINT chk_shipment_origin_iso
        CHECK (origin_iso IS NULL OR origin_iso ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT chk_shipment_destination_iso
        CHECK (destination_iso IS NULL OR destination_iso ~ '^[A-Z]{2}$');
--rollback ALTER TABLE shipment DROP CONSTRAINT IF EXISTS chk_shipment_origin_iso, DROP CONSTRAINT IF EXISTS chk_shipment_destination_iso;

--changeset screening:0008-chk-country-rule-iso
ALTER TABLE country_rule
    ADD CONSTRAINT chk_country_rule_origin_iso
        CHECK (origin_iso IS NULL OR origin_iso ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT chk_country_rule_destination_iso
        CHECK (destination_iso IS NULL OR destination_iso ~ '^[A-Z]{2}$');
--rollback ALTER TABLE country_rule DROP CONSTRAINT IF EXISTS chk_country_rule_origin_iso, DROP CONSTRAINT IF EXISTS chk_country_rule_destination_iso;

--changeset screening:0008-chk-screening-rule-iso
ALTER TABLE screening_rule
    ADD CONSTRAINT chk_screening_rule_origin_iso
        CHECK (origin_iso IS NULL OR origin_iso ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT chk_screening_rule_destination_iso
        CHECK (destination_iso IS NULL OR destination_iso ~ '^[A-Z]{2}$');
--rollback ALTER TABLE screening_rule DROP CONSTRAINT IF EXISTS chk_screening_rule_origin_iso, DROP CONSTRAINT IF EXISTS chk_screening_rule_destination_iso;
