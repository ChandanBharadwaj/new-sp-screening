from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_extra_types.country import CountryAlpha2


class PhraseGroup(BaseModel):
    """Compose multiple phrases under one rule.

    Exactly one of `any_of` or `all_of` is set; the rules engine combines per-phrase
    cross-encoder scores via max() for any_of, min() for all_of.
    """

    mode: Literal["any_of", "all_of"]
    phrases: list[str] = Field(min_length=1, max_length=10)


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Legacy single-phrase form. When phrase_group is set, this is still required
    # (used as the embedding seed and the human-facing "primary phrase") but it
    # need not be in phrase_group.phrases.
    phrase: str = Field(min_length=3)
    phrase_group: PhraseGroup | None = None
    threshold: float = Field(ge=0.0, le=1.0)
    conditions: dict[str, Any] | None = None
    origin_iso: CountryAlpha2 | None = None
    destination_iso: CountryAlpha2 | None = None
    active: bool = True
    created_by: str | None = None

    @field_validator("origin_iso", "destination_iso", mode="before")
    @classmethod
    def _upper_strip_iso(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @model_validator(mode="after")
    def _no_empty_group(self) -> "RuleIn":
        if self.phrase_group is not None and not self.phrase_group.phrases:
            raise ValueError("phrase_group.phrases cannot be empty")
        return self


class RuleOut(BaseModel):
    id: int
    name: str
    phrase: str
    phrase_group: dict[str, Any] | None = None
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
    per_phrase: list[dict[str, Any]] | None = None
    mode: str | None = None
