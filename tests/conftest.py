"""Pytest fixtures.

Most unit tests here are pure-Python and need no DB. DB-backed tests opt in by
requesting the `db` fixture, which expects `DATABASE_URL` to point at a reachable
Postgres (the CI liquibase job already provides one). If no DB is reachable, the
fixture skips.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session")
def database_url() -> str | None:
    return os.getenv("DATABASE_URL")


@pytest.fixture
async def db(database_url):
    if not database_url:
        pytest.skip("DATABASE_URL not set")
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        yield session
