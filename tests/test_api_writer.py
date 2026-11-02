"""Unit tests for the PostgreSQL writer using a fake psycopg connection (no DB)."""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from seed.api_writer import (
    API_TABLES,
    CONFLICT_TARGETS,
    PRIMARY_KEYS,
    ResetNotAllowedError,
    SchemaNotReadyError,
    assert_reset_allowed,
    build_upsert_statement,
    write_api_dataset,
)
from seed.faker_generators import AgroSenseFakerGenerator
from seed.run_seed import SeedConfig, run_seed


def _render(statement: Any) -> str:
    return statement if isinstance(statement, str) else statement.as_string(None)


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, statement: Any, params: Any = None) -> None:
        text = _render(statement)
        self.conn.executed.append((text, params))
        if "to_regclass" in text:
            self._result = [(t,) for t in self.conn.missing_tables]

    def executemany(self, statement: Any, rows: list[tuple[Any, ...]]) -> None:
        self.conn.executemany_calls.append((_render(statement), list(rows)))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result


class FakeConnection:
    def __init__(self, dbname: str = "agrosense_db", missing_tables: tuple[str, ...] = ()):
        self.info = SimpleNamespace(dbname=dbname)
        self.missing_tables = list(missing_tables)
        self.executed: list[tuple[str, Any]] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []
        self.urls: list[str] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def connect(self, url: str) -> FakeConnection:
        self.urls.append(url)
        return self


@pytest.fixture(scope="module")
def dataset() -> dict[str, list[dict[str, Any]]]:
    return AgroSenseFakerGenerator(seed=42).generate_all(mode="dev", farms_count=20, pilot_count=20)


def test_upsert_uses_documented_business_keys_with_unique_constraints() -> None:
    expected = {
        "farms": "farm_code",
        "producers": "document_number",
        "international_buyers": "client_id",
        "export_batches": "batch_code",
        "coffee_varieties": "variety_name",
    }
    for table, key in expected.items():
        sql_text = _render(build_upsert_statement(table))
        assert f'ON CONFLICT ("{key}")' in sql_text
        # The PK and the conflict key are never rewritten on conflict.
        assert f'"{PRIMARY_KEYS[table]}" = EXCLUDED' not in sql_text
        assert f'"{key}" = EXCLUDED' not in sql_text


def test_upsert_falls_back_to_pk_when_documented_key_has_no_constraint() -> None:
    assert CONFLICT_TARGETS["users"] == ("user_id",)
    assert CONFLICT_TARGETS["municipalities"] == ("municipality_id",)
    assert "DO NOTHING" in _render(build_upsert_statement("municipalities"))
    assert "DO NOTHING" in _render(build_upsert_statement("batch_farm_compositions"))
    farms_sql = _render(build_upsert_statement("farms"))
    assert 'DO UPDATE SET "producer_id" = EXCLUDED."producer_id"' in farms_sql


def test_overlap_geometry_is_bound_through_st_geomfromewkt() -> None:
    sql_text = _render(build_upsert_statement("farm_reserve_overlaps"))
    assert "ST_GeomFromEWKT(%s)" in sql_text


def test_write_api_dataset_inserts_all_tables_in_fk_order(dataset) -> None:
    conn = FakeConnection()
    counts = write_api_dataset(
        dataset, "postgresql+psycopg://u:p@h:5432/agrosense_db", connect=conn.connect
    )

    assert conn.urls == ["postgresql://u:p@h:5432/agrosense_db"]
    inserted_tables = [stmt.split('"')[1] for stmt, _ in conn.executemany_calls]
    non_empty = [t for t in API_TABLES if counts[t] > 0]
    assert inserted_tables == non_empty  # dependency order == API_TABLES order
    for stmt, rows in conn.executemany_calls:
        table = stmt.split('"')[1]
        assert len(rows) == counts[table]
        assert all(len(row) == len(API_TABLES[table]) for row in rows)
    assert not any("TRUNCATE" in stmt for stmt, _ in conn.executed)
    assert counts["farms"] == 20
    assert counts["farm_reserve_overlaps"] >= 1


def test_write_api_dataset_fails_fast_without_api_schema(dataset) -> None:
    conn = FakeConnection(missing_tables=("farms",))
    with pytest.raises(SchemaNotReadyError, match="alembic upgrade head"):
        write_api_dataset(dataset, "postgresql://x/agrosense_db", connect=conn.connect)
    assert conn.executemany_calls == []


def test_reset_is_refused_on_non_test_database(dataset) -> None:
    conn = FakeConnection(dbname="agrosense_db")
    with pytest.raises(ResetNotAllowedError):
        write_api_dataset(dataset, "postgresql://x/agrosense_db", reset=True, connect=conn.connect)
    assert not any("TRUNCATE" in stmt for stmt, _ in conn.executed)
    assert conn.executemany_calls == []


def test_reset_allowed_on_test_database(dataset) -> None:
    conn = FakeConnection(dbname="agrosense_test_db")
    write_api_dataset(dataset, "postgresql://x/agrosense_test_db", reset=True, connect=conn.connect)
    truncates = [stmt for stmt, _ in conn.executed if "TRUNCATE" in stmt]
    assert len(truncates) == 1
    assert "RESTART IDENTITY CASCADE" in truncates[0]


def test_reset_allowed_with_explicit_confirmation(monkeypatch) -> None:
    with pytest.raises(ResetNotAllowedError):
        assert_reset_allowed("agrosense_db")
    monkeypatch.setenv("SEED_RESET_CONFIRM_DB", "other_db")
    with pytest.raises(ResetNotAllowedError):
        assert_reset_allowed("agrosense_db")
    monkeypatch.setenv("SEED_RESET_CONFIRM_DB", "agrosense_db")
    assert_reset_allowed("agrosense_db")
    with pytest.raises(ResetNotAllowedError):
        assert_reset_allowed(None)


def test_conftest_scrubs_database_environment() -> None:
    assert "DATABASE_URL" not in os.environ
    assert "PGHOST" not in os.environ
    assert "TEST_DATABASE_URL" not in os.environ


def test_run_seed_does_not_touch_db_without_database_url(monkeypatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("seed.run_seed.write_api_dataset", lambda *a, **k: calls.append(a))
    config = SeedConfig(mode="dev", seed=42, defect_rate=0.05, farms=10, pilot_farms=5)
    assert run_seed(config) == 0
    assert calls == []
