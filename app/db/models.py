import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CHAR,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
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
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    origin_iso: Mapped[str | None] = mapped_column(CHAR(2))
    destination_iso: Mapped[str | None] = mapped_column(CHAR(2))
    sanctioned_commodity_id: Mapped[int | None] = mapped_column(ForeignKey("sanctioned_commodity.id"))
    restriction_type: Mapped[str | None] = mapped_column(String(32))
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScreeningRule(Base):
    __tablename__ = "screening_rule"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phrase: Mapped[str] = mapped_column(Text, nullable=False)
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
