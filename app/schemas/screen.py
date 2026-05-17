from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ShipmentIn(BaseModel):
    external_ref: str | None = None
    commodity_text: str
    cargo_text: str | None = None
    origin_iso: str | None = None
    destination_iso: str | None = None
    shipment_value: float | None = None
    currency: str | None = None
    metadata: dict[str, Any] | None = None


class HsCandidate(BaseModel):
    hs_code: str
    level: str
    chapter: str | None = None
    heading: str | None = None
    title: str
    score: float
    score_components: dict[str, Any] = Field(default_factory=dict)


class ConfidenceMetrics(BaseModel):
    top1_score: float | None = None
    top1_minus_top2: float | None = None
    entropy_topk: float | None = None
    chapter_consensus: float | None = None
    cross_source_agreement: bool | None = None


class HsClassification(BaseModel):
    top_candidates: list[HsCandidate]
    chapter_distribution: dict[str, float]
    confidence_metrics: ConfidenceMetrics
    # Abstention surface (spec-compliant; not a disposition).
    abstained: bool = False
    abstain_reason: str | None = None
    fallback_level: int | None = None
    fallback_candidate: HsCandidate | None = None
    # Multi-commodity decomposition output (one HsCandidate per detected commodity).
    multi_commodity: list[HsCandidate] | None = None


class ScreeningResultOut(BaseModel):
    shipment_id: UUID
    engine_version: str
    hs_classification: HsClassification
    sanction_matches: list[dict[str, Any]] = Field(default_factory=list)
    rule_matches: list[dict[str, Any]] = Field(default_factory=list)
    extracted_entities: dict[str, Any]
    latency_ms: dict[str, int]
    # Model + refdata version snapshot for the screening.
    versions: dict[str, Any] | None = None
