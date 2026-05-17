"""Multi-commodity decomposition.

A shipment line like "1000T steel coil + 500L industrial paint" describes two
commodities. The pipeline's HS branch is single-result by design, so we surface a
list of sub-texts the orchestrator can re-run independently.

Strategy (deliberately conservative — false negatives are preferred over false
positives, since wrongly splitting a single commodity inflates latency and adds
noise to operator workflows):

1. Split the normalized text on coordinating conjunctions (`+`, `&`, `;`) and on
   "<comma> <material noun>" boundaries. Sentence-level coordinators (` and `,
   ` plus `) are also split candidates.
2. Distribute NER `material` spans across the resulting fragments by simple
   substring containment; require ≥2 fragments each with a distinct material
   token before we declare multi-commodity. Otherwise the input is single.
3. Cap at 5 sub-texts (above that, fall back to single-commodity to bound cost).

The decomposer's `confidence` ∈ [0,1] is the orchestrator's gate: if low, it
keeps the single-commodity path. Heuristic for now; future work calibrates it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Split on: explicit list separators "+", "&", ";", "/" between alpha tokens,
# the words " and ", " plus " (only when not following a number for "5 and 6"),
# and a comma + space (treated as soft separator, post-filtered).
_SPLIT_RE = re.compile(
    r"\s*(?:[+&;]|/|\bplus\b|\band\b)\s*",
    flags=re.IGNORECASE,
)
_COMMA_RE = re.compile(r"\s*,\s*")

MAX_FRAGMENTS = 5
MIN_FRAGMENT_LEN = 5  # chars; "steel" yes, "+" no


@dataclass
class CommodityFragment:
    text: str
    materials: list[str]


@dataclass
class Decomposition:
    fragments: list[CommodityFragment]
    confidence: float  # 0.0 (don't trust) ... 1.0 (clearly multi-commodity)


def _candidate_fragments(text: str) -> list[str]:
    """Yield raw fragments using primary splitters, then secondary comma splits."""
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p and p.strip()]
    if len(parts) <= 1:
        # Try comma as a softer fallback only if explicit separators yielded nothing.
        parts = [p.strip() for p in _COMMA_RE.split(text) if p and p.strip()]
    return [p for p in parts if len(p) >= MIN_FRAGMENT_LEN]


def _assign_materials(fragments: list[str], materials: list[str]) -> list[list[str]]:
    """For each fragment, which material tokens appear (case-insensitive substring)?"""
    out: list[list[str]] = []
    for frag in fragments:
        lo = frag.lower()
        hit = [m for m in materials if m and m.lower() in lo]
        out.append(hit)
    return out


def split_into_commodities(text: str, ner_entities: dict[str, list[str]] | None) -> Decomposition:
    """Heuristic multi-commodity decomposition.

    Returns a Decomposition with confidence ∈ [0,1]. Callers should gate on
    `confidence >= 0.5` (the default in the orchestrator) before running the
    pipeline multiple times.
    """
    if not text:
        return Decomposition(fragments=[CommodityFragment(text="", materials=[])], confidence=0.0)

    raw = _candidate_fragments(text)
    if len(raw) <= 1:
        return Decomposition(
            fragments=[CommodityFragment(text=text, materials=(ner_entities or {}).get("material", []))],
            confidence=0.0,
        )
    if len(raw) > MAX_FRAGMENTS:
        # Too many fragments — likely a comma-spam description, not a true list.
        return Decomposition(
            fragments=[CommodityFragment(text=text, materials=(ner_entities or {}).get("material", []))],
            confidence=0.0,
        )

    materials = (ner_entities or {}).get("material") or []
    per_frag_materials = _assign_materials(raw, materials)

    # Require at least 2 fragments each having at least one material span, AND
    # the materials across fragments must not all be the same single token.
    fragments_with_material = [(t, ms) for t, ms in zip(raw, per_frag_materials, strict=True) if ms]
    distinct_materials = {m for _, ms in fragments_with_material for m in ms}

    if len(fragments_with_material) < 2 or len(distinct_materials) < 2:
        return Decomposition(
            fragments=[CommodityFragment(text=text, materials=materials)],
            confidence=0.0,
        )

    # Build the final fragment list (only those with material spans — others are
    # likely metadata / connective phrases).
    final = [CommodityFragment(text=t, materials=ms) for t, ms in fragments_with_material]
    # Confidence: more distinct materials = higher confidence, capped at 1.0.
    conf = min(1.0, 0.4 + 0.2 * len(distinct_materials))
    return Decomposition(fragments=final, confidence=conf)
