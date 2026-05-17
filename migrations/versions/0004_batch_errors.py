"""batch job per-row error persistence

Revision ID: 0004_batch_errors
Revises: 0003_review_fixes
Create Date: 2026-05-17

`BatchJob.failed_rows` is a count only — when a CSV upload fails partway,
operators see "N failed" and have no way to fix the bad rows. This adds a
per-row error table the worker writes to when a screen attempt raises.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_batch_errors"
down_revision = "0003_review_fixes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "batch_job_error",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("batch_job.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer, nullable=False),
        sa.Column("raw_row", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "CREATE INDEX ix_batch_job_error_batch "
        "ON batch_job_error (batch_id, row_index);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_batch_job_error_batch;")
    op.execute("DROP TABLE IF EXISTS batch_job_error CASCADE;")
