--liquibase formatted sql

-- Item 3 prep: move the two cross_source_agreement floors out of confidence.py
-- constants into policy_parameter so the calibration pipeline can sweep + apply
-- them like every other DB-backed threshold.

--changeset screening:0012-confidence-floors
INSERT INTO policy_parameter (scope, name, value) VALUES
    ('confidence', 'cross_source_dense_floor', '0.4'),
    ('confidence', 'cross_source_ce_floor',    '0.4');
--rollback DELETE FROM policy_parameter WHERE scope = 'confidence' AND name IN ('cross_source_dense_floor','cross_source_ce_floor');
