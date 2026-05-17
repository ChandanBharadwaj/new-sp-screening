import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBED_DIM = 384


class HsCode(Base):
    __tablename__ = "hs_code"
    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 2 | 4 | 6
    parent_code: Mapped[str | None] = mapped_column(String(10), ForeignKey("hs_code.code"))
    chapter: Mapped[str] = mapped_column(String(2), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    chapter_notes: Mapped[str | None] = mapped_column(Text)
    section_notes: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    description_tsv = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HsEntityIndex(Base):
    __tablename__ = "hs_entity_index"
    hs_code: Mapped[str] = mapped_column(String(10), ForeignKey("hs_code.code"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_value: Mapped[str] = mapped_column(Text, primary_key=True)
    weight: Mapped[float] = mapped_column(nullable=True)


class HsTrainingExample(Base):
    __tablename__ = "hs_training_example"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_id",
            "hs_code",
            name="uq_hs_training_example",
            postgresql_nulls_not_distinct=True,
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hs_code: Mapped[str | None] = mapped_column(String(10), ForeignKey("hs_code.code"))
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    description_tsv = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SanctionedCommodity(Base):
    __tablename__ = "sanctioned_commodity"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_record_id",
            name="uq_sanctioned_commodity_source_recid",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    source_record_id: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hs_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))
    restriction_type: Mapped[str | None] = mapped_column(String(32))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    provenance_url: Mapped[str | None] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    description_tsv = mapped_column(TSVECTOR, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CountryRule(Base):
    __tablename__ = "country_rule"
    __table_args__ = (
        UniqueConstraint(
            "origin_iso",
            "destination_iso",
            "sanctioned_commodity_id",
            "restriction_type",
            name="uq_country_rule",
            postgresql_nulls_not_distinct=True,
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    origin_iso: Mapped[str | None] = mapped_column(CHAR(2))
    destination_iso: Mapped[str | None] = mapped_column(CHAR(2))
    sanctioned_commodity_id: Mapped[int | None] = mapped_column(ForeignKey("sanctioned_commodity.id"))
    restriction_type: Mapped[str | None] = mapped_column(String(32))
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SanctionedCommodityAlias(Base):
    """Alias / AKA / transliteration row joined to a sanctioned commodity.

    Populated by ingesters that publish multiple names per entity (notably OFAC SDN's
    `alt.csv`). The trgm GIN index on `alias` powers fast fuzzy lookup at screening
    time without forcing each ingester to denormalize aliases into the main
    description column. The unique constraint on (parent, alias) makes ingester
    re-runs idempotent via ON CONFLICT DO NOTHING.
    """

    __tablename__ = "sanctioned_commodity_alias"
    __table_args__ = (
        UniqueConstraint(
            "sanctioned_commodity_id", "alias", name="uq_alias_per_commodity"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sanctioned_commodity_id: Mapped[int] = mapped_column(
        ForeignKey("sanctioned_commodity.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_kind: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScreeningRule(Base):
    __tablename__ = "screening_rule"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phrase: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional group form: {"any_of": [...]} or {"all_of": [...]}.
    # When set, the per-phrase cross-encoder scores combine via max() / min() respectively.
    # When null, only `phrase` is scored (legacy single-phrase rule).
    phrase_group: Mapped[dict | None] = mapped_column(JSONB)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    threshold: Mapped[float] = mapped_column(nullable=False)
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    origin_iso: Mapped[str | None] = mapped_column(CHAR(2))
    destination_iso: Mapped[str | None] = mapped_column(CHAR(2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Shipment(Base):
    __tablename__ = "shipment"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_ref: Mapped[str | None] = mapped_column(Text)
    commodity_text: Mapped[str] = mapped_column(Text, nullable=False)
    cargo_text: Mapped[str | None] = mapped_column(Text)
    origin_iso: Mapped[str | None] = mapped_column(CHAR(2))
    destination_iso: Mapped[str | None] = mapped_column(CHAR(2))
    shipment_value: Mapped[float | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScreeningResult(Base):
    __tablename__ = "screening_result"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shipment.id"))
    hs_candidates: Mapped[dict | None] = mapped_column(JSONB)
    sanction_matches: Mapped[dict | None] = mapped_column(JSONB)
    rule_matches: Mapped[dict | None] = mapped_column(JSONB)
    extracted_entities: Mapped[dict | None] = mapped_column(JSONB)
    confidence_metrics: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[dict | None] = mapped_column(JSONB)
    engine_version: Mapped[str | None] = mapped_column(Text)
    # Stamped per screening: engine, model hashes/IDs, refdata refresh timestamps.
    # Shape: {"engine": "...", "ltr_hash": "sha256:...", "reranker": "...", "embedder": "...",
    #         "ner": "...", "refdata": {"OFAC_SDN": "2026-05-12T03:00:00+00:00", ...}}
    versions: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedbackEvent(Base):
    __tablename__ = "feedback_event"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    result_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("screening_result.id"))
    analyst_id: Mapped[str | None] = mapped_column(Text)
    event_type: Mapped[str | None] = mapped_column(String(32))
    before_value: Mapped[dict | None] = mapped_column(JSONB)
    after_value: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Operational tables (not in README §8 — added for the Status UI)


class RefdataRun(Base):
    __tablename__ = "refdata_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_upserted: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)


class EvalRun(Base):
    __tablename__ = "eval_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    classifier: Mapped[str] = mapped_column(String(64), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    top1_subheading: Mapped[float | None] = mapped_column()
    top3_subheading: Mapped[float | None] = mapped_column()
    top1_chapter: Mapped[float | None] = mapped_column()
    mrr: Mapped[float | None] = mapped_column()
    p50_ms: Mapped[float | None] = mapped_column()
    p95_ms: Mapped[float | None] = mapped_column()
    p99_ms: Mapped[float | None] = mapped_column()
    n_examples: Mapped[int | None] = mapped_column()
    report_json: Mapped[dict | None] = mapped_column(JSONB)


class BatchJob(Base):
    __tablename__ = "batch_job"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str | None] = mapped_column(Text)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    completed_rows: Mapped[int] = mapped_column(Integer, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | running | done | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BatchJobError(Base):
    __tablename__ = "batch_job_error"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("batch_job.id", ondelete="CASCADE"), nullable=False
    )
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_row: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TrainingRun(Base):
    __tablename__ = "training_run"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # "ltr"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | failed
    error_message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSONB)
    artifact_path: Mapped[str | None] = mapped_column(Text)
    dataset_csv_path: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict | None] = mapped_column(JSONB)


class EvalJob(Base):
    __tablename__ = "eval_job"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="running")
    error_message: Mapped[str | None] = mapped_column(Text)
    classifier: Mapped[str] = mapped_column(String(64), nullable=False)
    split: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_n: Mapped[int | None] = mapped_column(Integer)
    eval_run_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("eval_run.id"))


class JobLog(Base):
    __tablename__ = "job_log"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_table: Mapped[str] = mapped_column(String(32), nullable=False)  # refdata_run|training_run|eval_job
    run_id: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(String(8), default="info")
    line: Mapped[str] = mapped_column(Text, nullable=False)


class Threshold(Base):
    __tablename__ = "threshold"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(String(16), default="ui")  # yaml_seed | ui


class SanctionsRuleConfig(Base):
    """Per-source toggle + tuning for the ScreeningRule materializer.

    One row per sanctions source key (e.g. 'OFAC_SDN', 'IRAN'). When `enabled`,
    `app.refdata.sanctions.materialize_rules` upserts ScreeningRule rows derived
    from the source's `sanctioned_commodity` + `country_rule` data after each
    ingest. Off by default so flipping a source on is a deliberate operator action.
    """

    __tablename__ = "sanctions_rule_config"
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_threshold: Mapped[float] = mapped_column(nullable=False, default=0.55)
    # 'description_only' | 'with_aliases' | 'split_lists'
    phrase_strategy: Mapped[str] = mapped_column(Text, nullable=False, default="split_lists")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
