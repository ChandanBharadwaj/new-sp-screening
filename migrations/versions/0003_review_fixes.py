"""review fixes: version stamping, rule composition, sanctioned commodity aliases

Revision ID: 0003_review_fixes
Revises: 0002_training_eval_ui
Create Date: 2026-05-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_review_fixes"
down_revision = "0002_training_eval_ui"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) ScreeningResult: model + refdata version stamping (Fix #2).
    op.add_column(
        "screening_result",
        sa.Column("versions", postgresql.JSONB, nullable=True),
    )

    # 2) ScreeningRule: any_of / all_of phrase composition (Fix #6).
    op.add_column(
        "screening_rule",
        sa.Column("phrase_group", postgresql.JSONB, nullable=True),
    )

    # 3) Sanctioned commodity aliases (Fix #7 + needed by Fix #1 OFAC ingest).
    op.create_table(
        "sanctioned_commodity_alias",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "sanctioned_commodity_id",
            sa.BigInteger,
            sa.ForeignKey("sanctioned_commodity.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text, nullable=False),
        sa.Column("alias_kind", sa.String(16), nullable=True),  # "aka" | "fka" | "translit"
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "CREATE INDEX ix_alias_sanctioned_commodity_id "
        "ON sanctioned_commodity_alias (sanctioned_commodity_id);"
    )
    op.execute(
        "CREATE INDEX ix_alias_alias_trgm "
        "ON sanctioned_commodity_alias USING gin (alias gin_trgm_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_alias_alias_trgm;")
    op.execute("DROP INDEX IF EXISTS ix_alias_sanctioned_commodity_id;")
    op.execute("DROP TABLE IF EXISTS sanctioned_commodity_alias CASCADE;")
    op.drop_column("screening_rule", "phrase_group")
    op.drop_column("screening_result", "versions")
