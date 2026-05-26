"""Single persistence path for screening results, shared by the sync (API) and
batch (worker) paths.

Item 12: the batch path previously hand-built `ScreeningResult` and dropped the
`versions` audit blob, so 99% of decisions had worse lineage than the 1% sync path.
Both paths now build the row here, and `versions` is required — a result with no
model/refdata version stamp cannot be persisted.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.models import ScreeningResult


def build_screening_result(shipment_id: UUID, payload: dict[str, Any]) -> ScreeningResult:
    """Construct a ScreeningResult from an orchestrator payload.

    Raises ValueError if the version stamp is missing so neither path can persist
    an unauditable decision. `run_screen` always populates `payload["versions"]`
    (falling back to compute_static()), so a missing value signals a real defect.
    """
    versions = payload.get("versions")
    if not versions:
        raise ValueError(
            f"refusing to persist screening result for shipment {shipment_id}: "
            "missing version stamp (audit lineage required)"
        )
    return ScreeningResult(
        shipment_id=shipment_id,
        hs_candidates=payload["hs_classification"],
        sanction_matches={"items": payload["sanction_matches"]},
        rule_matches={"items": payload["rule_matches"]},
        extracted_entities=payload["extracted_entities"],
        confidence_metrics=payload["hs_classification"]["confidence_metrics"],
        latency_ms=payload["latency_ms"],
        engine_version=payload["engine_version"],
        versions=versions,
    )
