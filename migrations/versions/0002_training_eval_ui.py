"""training/eval UI tables: training_run, eval_job, job_log, threshold

Revision ID: 0002_training_eval_ui
Revises: 0001_init
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_training_eval_ui"
down_revision = "0001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_run",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), server_default="running"),
        sa.Column("error_message", sa.Text),
        sa.Column("params", postgresql.JSONB),
        sa.Column("artifact_path", sa.Text),
        sa.Column("dataset_csv_path", sa.Text),
        sa.Column("metrics", postgresql.JSONB),
    )

    op.create_table(
        "eval_job",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), server_default="running"),
        sa.Column("error_message", sa.Text),
        sa.Column("classifier", sa.String(64), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("limit_n", sa.Integer),
        sa.Column("eval_run_id", sa.BigInteger, sa.ForeignKey("eval_run.id")),
    )

    op.create_table(
        "job_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_table", sa.String(32), nullable=False),
        sa.Column("run_id", sa.BigInteger, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("level", sa.String(8), server_default="info"),
        sa.Column("line", sa.Text, nullable=False),
    )
    op.execute("CREATE INDEX job_log_run_id_idx ON job_log (run_table, run_id, id);")

    op.create_table(
        "threshold",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("source", sa.String(16), server_default="ui"),
    )

    op.execute("CREATE INDEX training_run_started ON training_run (started_at DESC);")
    op.execute("CREATE INDEX eval_job_started ON eval_job (started_at DESC);")


def downgrade() -> None:
    for tbl in ["job_log", "threshold", "eval_job", "training_run"]:
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
