"""CSV serialization for batch failure drill-down — extracted so tests can
exercise it without importing the routes module (which pulls in arq / redis)."""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable

# Column order matches what `upload` expects, plus an `error` column — so an
# operator can take the downloaded errors CSV, fix the bad rows, and re-upload
# without remapping columns.
ERRORS_CSV_FIELDS = [
    "row_index",
    "external_ref",
    "commodity_text",
    "cargo_text",
    "origin_iso",
    "destination_iso",
    "error",
]


def serialize_errors_csv(rows: Iterable[object]) -> str:
    """Render BatchJobError rows as a CSV operators can fix and re-upload.

    Rows need only have `.row_index`, `.raw_row` (dict or None), and
    `.error_message` attributes — not necessarily the SQLAlchemy class itself.
    """
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ERRORS_CSV_FIELDS)
    writer.writeheader()
    for r in rows:
        raw = getattr(r, "raw_row", None) or {}
        writer.writerow(
            {
                "row_index": r.row_index,
                "external_ref": raw.get("external_ref") or "",
                "commodity_text": raw.get("commodity_text") or "",
                "cargo_text": raw.get("cargo_text") or "",
                "origin_iso": raw.get("origin_iso") or "",
                "destination_iso": raw.get("destination_iso") or "",
                "error": r.error_message,
            }
        )
    return buf.getvalue()
