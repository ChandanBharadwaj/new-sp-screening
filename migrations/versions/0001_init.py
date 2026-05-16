"""initial schema with pgvector + tsvector

Revision ID: 0001_init
Revises:
Create Date: 2026-05-16

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None

EMBED_DIM = 384


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    op.create_table(
        "hs_code",
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("level", sa.SmallInteger, nullable=False),
        sa.Column("parent_code", sa.String(10), sa.ForeignKey("hs_code.code"), nullable=True),
        sa.Column("chapter", sa.String(2), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("chapter_notes", sa.Text),
        sa.Column("section_notes", sa.Text),
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("description_tsv", postgresql.TSVECTOR),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "hs_entity_index",
        sa.Column("hs_code", sa.String(10), sa.ForeignKey("hs_code.code"), primary_key=True),
        sa.Column("entity_type", sa.String(32), primary_key=True),
        sa.Column("entity_value", sa.Text, primary_key=True),
        sa.Column("weight", sa.REAL),
    )

    op.create_table(
        "hs_training_example",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Text),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("hs_code", sa.String(10), sa.ForeignKey("hs_code.code")),
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("description_tsv", postgresql.TSVECTOR),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "sanctioned_commodity",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("source_record_id", sa.Text),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("hs_codes", postgresql.ARRAY(sa.String(10))),
        sa.Column("restriction_type", sa.String(32)),
        sa.Column("effective_from", sa.Date),
        sa.Column("effective_to", sa.Date),
        sa.Column("provenance_url", sa.Text),
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("description_tsv", postgresql.TSVECTOR),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "country_rule",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("origin_iso", sa.CHAR(2)),
        sa.Column("destination_iso", sa.CHAR(2)),
        sa.Column("sanctioned_commodity_id", sa.BigInteger, sa.ForeignKey("sanctioned_commodity.id")),
        sa.Column("restriction_type", sa.String(32)),
        sa.Column("conditions", postgresql.JSONB),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "screening_rule",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("phrase", sa.Text, nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM)),
        sa.Column("threshold", sa.REAL, nullable=False),
        sa.Column("conditions", postgresql.JSONB),
        sa.Column("origin_iso", sa.CHAR(2)),
        sa.Column("destination_iso", sa.CHAR(2)),
        sa.Column("active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_by", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "shipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("external_ref", sa.Text),
        sa.Column("commodity_text", sa.Text, nullable=False),
        sa.Column("cargo_text", sa.Text),
        sa.Column("origin_iso", sa.CHAR(2)),
        sa.Column("destination_iso", sa.CHAR(2)),
        sa.Column("shipment_value", sa.Numeric(18, 2)),
        sa.Column("currency", sa.CHAR(3)),
        sa.Column("metadata", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "screening_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shipment.id")),
        sa.Column("hs_candidates", postgresql.JSONB),
        sa.Column("sanction_matches", postgresql.JSONB),
        sa.Column("rule_matches", postgresql.JSONB),
        sa.Column("extracted_entities", postgresql.JSONB),
        sa.Column("confidence_metrics", postgresql.JSONB),
        sa.Column("latency_ms", postgresql.JSONB),
        sa.Column("engine_version", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "feedback_event",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("screening_result.id")),
        sa.Column("analyst_id", sa.Text),
        sa.Column("event_type", sa.String(32)),
        sa.Column("before_value", postgresql.JSONB),
        sa.Column("after_value", postgresql.JSONB),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Operational tables (Status UI)
    op.create_table(
        "refdata_run",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_upserted", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(16), server_default="running"),
        sa.Column("error_message", sa.Text),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "eval_run",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ran_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("classifier", sa.String(64), nullable=False),
        sa.Column("split", sa.String(16), nullable=False),
        sa.Column("top1_subheading", sa.Float),
        sa.Column("top3_subheading", sa.Float),
        sa.Column("top1_chapter", sa.Float),
        sa.Column("mrr", sa.Float),
        sa.Column("p50_ms", sa.Float),
        sa.Column("p95_ms", sa.Float),
        sa.Column("p99_ms", sa.Float),
        sa.Column("n_examples", sa.Integer),
        sa.Column("report_json", postgresql.JSONB),
    )

    op.create_table(
        "batch_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("filename", sa.Text),
        sa.Column("total_rows", sa.Integer, server_default="0"),
        sa.Column("completed_rows", sa.Integer, server_default="0"),
        sa.Column("failed_rows", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # HNSW + GIN indexes
    op.execute("CREATE INDEX hs_code_embedding_hnsw ON hs_code USING hnsw (embedding vector_cosine_ops);")
    op.execute("CREATE INDEX hs_code_tsv_gin ON hs_code USING gin (description_tsv);")
    op.execute("CREATE INDEX hs_training_example_embedding_hnsw ON hs_training_example USING hnsw (embedding vector_cosine_ops);")
    op.execute("CREATE INDEX hs_training_example_tsv_gin ON hs_training_example USING gin (description_tsv);")
    op.execute("CREATE INDEX sanctioned_commodity_embedding_hnsw ON sanctioned_commodity USING hnsw (embedding vector_cosine_ops);")
    op.execute("CREATE INDEX sanctioned_commodity_tsv_gin ON sanctioned_commodity USING gin (description_tsv);")
    op.execute("CREATE INDEX screening_rule_embedding_hnsw ON screening_rule USING hnsw (embedding vector_cosine_ops);")

    # Helpful operational indexes
    op.execute("CREATE INDEX refdata_run_source_started ON refdata_run (source, started_at DESC);")
    op.execute("CREATE INDEX eval_run_classifier_split_ran ON eval_run (classifier, split, ran_at DESC);")
    op.execute("CREATE INDEX hs_code_chapter ON hs_code (chapter);")
    op.execute("CREATE INDEX hs_code_level ON hs_code (level);")
    op.execute("CREATE INDEX hs_training_example_source ON hs_training_example (source);")
    op.execute("CREATE INDEX screening_result_shipment ON screening_result (shipment_id);")


def downgrade() -> None:
    for tbl in [
        "feedback_event",
        "screening_result",
        "shipment",
        "screening_rule",
        "country_rule",
        "sanctioned_commodity",
        "hs_training_example",
        "hs_entity_index",
        "hs_code",
        "refdata_run",
        "eval_run",
        "batch_job",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
