"""Shared pytest configuration.

Safety: unit tests must NEVER reach a real PostgreSQL. ``run_seed`` writes to the
database whenever ``DATABASE_URL`` is set, so every test runs with the connection
environment scrubbed. Integration tests opt in explicitly through the
``TEST_DATABASE_URL`` variable (consumed by the ``test_database_url`` fixture),
which must point to a disposable test database (``*_test_db``).
"""

from __future__ import annotations

import os

import pytest

# Variables that could make the seed (psycopg/libpq) connect to a real database
# or authorise a destructive reset.
_SCRUBBED_ENV_VARS = (
    "DATABASE_URL",
    "AGROSENSE_DATABASE_URL",
    "SEED_RESET_CONFIRM_DB",
    "SEED_RESET_BEFORE_RUN",
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGPASSFILE",
)

# Captured at import time, before the autouse fixture scrubs the environment.
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(autouse=True)
def _isolate_from_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every DB connection variable so no unit test can hit PostgreSQL."""
    for name in _SCRUBBED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)


@pytest.fixture
def test_database_url() -> str:
    """Opt-in URL for integration tests; skips unless TEST_DATABASE_URL is set."""
    if not _TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL no configurada: se omiten pruebas de integración.")
    return _TEST_DATABASE_URL
