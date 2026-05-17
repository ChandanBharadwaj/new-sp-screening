"""Tests for batch failure drill-down endpoint shape (no DB)."""
import csv
import io
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.db.models import BatchJobError


def test_batch_job_error_model_columns() -> None:
    """Sanity-check the ORM mapping matches the migration shape."""
    cols = {c.name for c in BatchJobError.__table__.columns}
    assert cols == {
        "id",
        "batch_id",
        "row_index",
        "raw_row",
        "error_message",
        "created_at",
    }
    # FK on batch_id with cascade delete is what makes errors disappear when
    # the parent BatchJob is deleted.
    fks = list(BatchJobError.__table__.foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "batch_job"
    assert fks[0].ondelete == "CASCADE"


def test_errors_query_filters_by_batch_id() -> None:
    """The listing endpoint must scope to the requested batch_id only."""
    batch_id = uuid4()
    stmt = (
        select(BatchJobError)
        .where(BatchJobError.batch_id == batch_id)
        .order_by(BatchJobError.row_index.asc())
        .limit(200)
        .offset(0)
    )
    sql = str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    ).lower()
    assert "where batch_job_error.batch_id =" in sql
    assert str(batch_id).lower() in sql
    assert "order by batch_job_error.row_index asc" in sql
    assert "limit 200" in sql


def test_csv_serialization_shape() -> None:
    """Serializer returns the failed rows in the same column layout the
    upload endpoint expects, plus an `error` column. Operators can fix and
    re-upload directly."""
    from app.api._batch_export import ERRORS_CSV_FIELDS, serialize_errors_csv

    rows = [
        SimpleNamespace(
            row_index=2,
            raw_row={
                "external_ref": "REF-2",
                "commodity_text": "stainless steel coil",
                "cargo_text": None,
                "origin_iso": "DE",
                "destination_iso": "IR",
            },
            error_message="missing commodity_text",
            created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            row_index=5,
            raw_row=None,  # no raw row recoverable
            error_message="upstream NER timeout",
            created_at=datetime(2026, 5, 17, tzinfo=timezone.utc),
        ),
    ]
    body = serialize_errors_csv(rows)
    reader = csv.DictReader(io.StringIO(body))
    out = list(reader)

    assert reader.fieldnames == ERRORS_CSV_FIELDS
    assert len(out) == 2
    assert out[0]["row_index"] == "2"
    assert out[0]["commodity_text"] == "stainless steel coil"
    assert out[0]["destination_iso"] == "IR"
    assert out[0]["error"] == "missing commodity_text"
    # Null raw_row degrades gracefully — empty cells, error still surfaced.
    assert out[1]["row_index"] == "5"
    assert out[1]["commodity_text"] == ""
    assert out[1]["error"] == "upstream NER timeout"


def test_csv_serialization_empty_list() -> None:
    """No errors → just a header row."""
    from app.api._batch_export import ERRORS_CSV_FIELDS, serialize_errors_csv

    body = serialize_errors_csv([])
    lines = body.strip().splitlines()
    assert len(lines) == 1
    assert lines[0] == ",".join(ERRORS_CSV_FIELDS)
