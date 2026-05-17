"""storage hardening: idempotent ingest + faster sanctions overlap + effective-date index

Revision ID: 0005_storage_hardening
Revises: 0004_batch_errors
Create Date: 2026-05-17

Adds the unique constraints needed to make `on_conflict_do_nothing` actually a
no-op on re-ingest (previously the only conflict target was the PK, which never
collides on autoincrement). Adds a GIN index on `sanctioned_commodity.hs_codes`
so the `&&` overlap join in app/pipeline/sanctions.py:36 becomes an index seek
instead of a sequential scan. Adds a btree on (effective_from, effective_to) for
the new effective-date filter applied at screen time.

Country_rule's unique constraint uses `NULLS NOT DISTINCT` (Postgres 15+) so that
two rules with identical NULL origin/destination/restriction values collide on
re-ingest; without it, Postgres treats each NULL as distinct and duplicates leak.

If the dev DB already has duplicates accumulated from prior ingests without
constraints, the `ADD CONSTRAINT` calls will fail. Operator instructions live in
RUNBOOK.md — the dedupe SQL is commented at the bottom of this file for copy/paste.
"""
from alembic import op

revision = "0005_storage_hardening"
down_revision = "0004_batch_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotency for sanctions ingesters. source_record_id is nullable; rows
    # without one continue to insert each run (no stable identity).
    op.execute(
        "ALTER TABLE sanctioned_commodity "
        "ADD CONSTRAINT uq_sanctioned_commodity_source_recid "
        "UNIQUE (source, source_record_id);"
    )

    # Country_rule: NULLS NOT DISTINCT so (NULL, 'RU', 42, 'blocked') collides
    # with itself on the second ingest.
    op.execute(
        "ALTER TABLE country_rule "
        "ADD CONSTRAINT uq_country_rule "
        "UNIQUE NULLS NOT DISTINCT "
        "(origin_iso, destination_iso, sanctioned_commodity_id, restriction_type);"
    )

    # HS training examples: a (source, source_id, hs_code) triplet identifies a
    # ruling/example uniquely; without this CROSS re-scrapes accumulate duplicates.
    op.execute(
        "ALTER TABLE hs_training_example "
        "ADD CONSTRAINT uq_hs_training_example "
        "UNIQUE NULLS NOT DISTINCT (source, source_id, hs_code);"
    )

    # GIN on hs_codes array — fixes the structured-overlap full-scan.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sanctioned_commodity_hs_codes_gin "
        "ON sanctioned_commodity USING gin (hs_codes);"
    )

    # Effective-date window: composite btree for the new predicate.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sanctioned_commodity_effective "
        "ON sanctioned_commodity (effective_from, effective_to);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sanctioned_commodity_effective;")
    op.execute("DROP INDEX IF EXISTS ix_sanctioned_commodity_hs_codes_gin;")
    op.execute("ALTER TABLE hs_training_example DROP CONSTRAINT IF EXISTS uq_hs_training_example;")
    op.execute("ALTER TABLE country_rule DROP CONSTRAINT IF EXISTS uq_country_rule;")
    op.execute("ALTER TABLE sanctioned_commodity DROP CONSTRAINT IF EXISTS uq_sanctioned_commodity_source_recid;")


# ----------------------------------------------------------------------------
# Pre-migration dedupe SQL — paste into psql if `ADD CONSTRAINT` fails.
# These keep the lowest-ctid row of each duplicate group; country_rule rows are
# repointed before the parent dedupe runs so the FK doesn't break.
#
#   UPDATE country_rule cr
#      SET sanctioned_commodity_id = keeper.id
#     FROM (
#       SELECT min(id) AS id, source, source_record_id
#         FROM sanctioned_commodity
#        WHERE source_record_id IS NOT NULL
#        GROUP BY source, source_record_id HAVING count(*) > 1
#     ) keeper
#     JOIN sanctioned_commodity dup
#       ON dup.source = keeper.source AND dup.source_record_id = keeper.source_record_id AND dup.id <> keeper.id
#    WHERE cr.sanctioned_commodity_id = dup.id;
#
#   DELETE FROM sanctioned_commodity sc
#    USING sanctioned_commodity sc2
#    WHERE sc.source = sc2.source
#      AND sc.source_record_id = sc2.source_record_id
#      AND sc.source_record_id IS NOT NULL
#      AND sc.id > sc2.id;
#
#   DELETE FROM country_rule cr
#    USING country_rule cr2
#    WHERE cr.sanctioned_commodity_id IS NOT DISTINCT FROM cr2.sanctioned_commodity_id
#      AND cr.origin_iso IS NOT DISTINCT FROM cr2.origin_iso
#      AND cr.destination_iso IS NOT DISTINCT FROM cr2.destination_iso
#      AND cr.restriction_type IS NOT DISTINCT FROM cr2.restriction_type
#      AND cr.id > cr2.id;
#
#   DELETE FROM hs_training_example a
#    USING hs_training_example b
#    WHERE a.source = b.source
#      AND a.source_id IS NOT DISTINCT FROM b.source_id
#      AND a.hs_code IS NOT DISTINCT FROM b.hs_code
#      AND a.id > b.id;
# ----------------------------------------------------------------------------
