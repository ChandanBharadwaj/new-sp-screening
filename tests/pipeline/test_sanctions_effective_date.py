"""Effective-date predicate is present in every sanctions retrieval path.

Hard to exercise without a live DB (the queries hit pgvector / tsvector / trgm),
so we assert at the SQL-string level that the effective-date clause is wired into
every query. The clause is a single shared constant so this regression-bait test
fires loudly if a future refactor forgets to splice it into a new path.
"""
from __future__ import annotations

from app.pipeline.sanctions import (
    ALIAS_QUERY,
    DENSE_QUERY,
    SPARSE_QUERY,
    STRUCTURED_QUERY,
)


def _sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


def test_structured_query_filters_effective_date() -> None:
    sql = _sql(STRUCTURED_QUERY)
    assert "effective_from" in sql
    assert "effective_to" in sql
    assert "CURRENT_DATE" in sql


def test_dense_query_filters_effective_date() -> None:
    sql = _sql(DENSE_QUERY)
    assert "effective_from" in sql
    assert "effective_to" in sql


def test_sparse_query_filters_effective_date() -> None:
    sql = _sql(SPARSE_QUERY)
    assert "effective_from" in sql
    assert "effective_to" in sql


def test_alias_query_filters_effective_date() -> None:
    sql = _sql(ALIAS_QUERY)
    assert "effective_from" in sql
    assert "effective_to" in sql
