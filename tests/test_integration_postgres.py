"""Real-PostgreSQL idempotency test (CT-06). Skipped unless TEST_DATABASE_URL is set.

Requirements: a disposable PostGIS database whose name ends with ``_test_db``
(e.g. ``agrosense_test_db``) with the API schema already migrated
(``alembic upgrade head`` from the API repository).

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/agrosense_test_db \
        uv run pytest tests/test_integration_postgres.py
"""

from __future__ import annotations

import pytest

from seed.api_writer import (
    is_test_database,
    normalize_database_url,
    table_fingerprints,
    write_api_dataset,
)
from seed.faker_generators import AgroSenseFakerGenerator

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_connection(test_database_url):
    psycopg = pytest.importorskip("psycopg")
    conn = psycopg.connect(normalize_database_url(test_database_url))
    try:
        if not is_test_database(conn.info.dbname):
            pytest.fail(
                f"TEST_DATABASE_URL apunta a {conn.info.dbname!r}; usa una BD *_test_db desechable."
            )
        yield conn
    finally:
        conn.close()


def _fingerprints(url: str) -> dict[str, tuple[int, str]]:
    import psycopg

    with psycopg.connect(normalize_database_url(url)) as conn:
        return table_fingerprints(conn)


def test_seed_twice_against_postgres_is_idempotent(test_database_url, pg_connection):
    dataset = AgroSenseFakerGenerator(seed=42).generate_all(mode="dev")

    write_api_dataset(dataset, test_database_url, reset=True)
    first = _fingerprints(test_database_url)

    write_api_dataset(dataset, test_database_url, reset=False)
    second = _fingerprints(test_database_url)

    assert first["farms"][0] == len(dataset["farms"])
    assert first["farm_reserve_overlaps"][0] == len(dataset["farm_reserve_overlaps"])
    for table, (count, checksum) in first.items():
        assert second[table][0] == count, f"Row inflation in {table} (CT-06)"
        assert second[table][1] == checksum, f"Checksum drift in {table} (CT-06)"


def test_overlap_geometry_matches_postgis_intersection(test_database_url, pg_connection):
    dataset = AgroSenseFakerGenerator(seed=42).generate_all(mode="dev")
    write_api_dataset(dataset, test_database_url, reset=True)

    with pg_connection.cursor() as cur:
        cur.execute(
            "SELECT bool_and(ST_IsValid(overlap_geometry)), "
            "bool_and(ST_SRID(overlap_geometry) = 4326), "
            "min(ST_Area(overlap_geometry::geography)) FROM farm_reserve_overlaps"
        )
        all_valid, all_4326, min_area_m2 = cur.fetchone()
    assert all_valid and all_4326
    assert min_area_m2 > 0
