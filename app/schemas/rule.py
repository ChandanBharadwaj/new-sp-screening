from typing import Any

from pydantic import BaseModel, Field


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phrase: str = Field(min_length=3)
    threshold: float = Field(ge=0.0, le=1.0)
    conditions: dict[str, Any] | None = None
    origin_iso: str | None = None
    destination_iso: str | None = None
    active: bool = True
    created_by: str | None = None


class RuleOut(BaseModel):
    id: int
    name: str
    phrase: str
    threshold: float
    conditions: dict[str, Any] | None
    origin_iso: str | None
    destination_iso: str | None
    active: bool
    version: int
    created_by: str | None
    created_at: str | None


class RuleTestIn(BaseModel):
    cargo_text: str
    shipment_value: float | None = None
    currency: str | None = None
    metadata: dict[str, Any] | None = None


class RuleTestOut(BaseModel):
    phrase_similarity: float
    threshold: float
    delta_above_threshold: float
    conditions_satisfied: bool
