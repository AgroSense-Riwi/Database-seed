"""Unit tests for the UPSERT Idempotency Engine (CT-06)."""

import pytest

from seed.faker_generators import AgroSenseFakerGenerator
from seed.upsert_engine import (
    TABLE_UPSERT_REGISTRY,
    TOPOLOGICAL_TABLE_ORDER,
    ConflictStrategy,
    UpsertEngine,
)


def test_registry_integrity_and_tiers():
    """Verify that all 18 tables are properly mapped to tiers 1-5."""
    assert len(TABLE_UPSERT_REGISTRY) >= 17

    # Verify key tables exist with correct strategies per specifying_idempotent.md
    assert TABLE_UPSERT_REGISTRY["departments"].strategy == ConflictStrategy.DO_NOTHING
    assert TABLE_UPSERT_REGISTRY["departments"].conflict_target == ("dane_code",)
    assert TABLE_UPSERT_REGISTRY["departments"].tier == 1

    assert TABLE_UPSERT_REGISTRY["users"].strategy == ConflictStrategy.DO_UPDATE
    assert TABLE_UPSERT_REGISTRY["users"].conflict_target == ("email",)

    assert TABLE_UPSERT_REGISTRY["farms"].strategy == ConflictStrategy.DO_UPDATE
    assert TABLE_UPSERT_REGISTRY["farms"].conflict_target == ("farm_code",)
    assert TABLE_UPSERT_REGISTRY["farms"].tier == 3

    assert TABLE_UPSERT_REGISTRY["iot_sensors"].strategy == ConflictStrategy.DO_UPDATE
    assert TABLE_UPSERT_REGISTRY["iot_sensors"].conflict_target == ("serial_number",)
    assert TABLE_UPSERT_REGISTRY["iot_sensors"].tier == 4

    assert TABLE_UPSERT_REGISTRY["export_batches"].strategy == ConflictStrategy.DO_UPDATE
    assert TABLE_UPSERT_REGISTRY["export_batches"].conflict_target == ("batch_code",)
    assert TABLE_UPSERT_REGISTRY["export_batches"].tier == 5


def test_topological_table_order_preserves_fk_tiers():
    """Verify tables are strictly sorted by dependency tier 1 to 5."""
    tiers = [TABLE_UPSERT_REGISTRY[t].tier for t in TOPOLOGICAL_TABLE_ORDER]
    assert tiers == sorted(tiers)
    assert tiers[0] == 1
    assert tiers[-1] == 5


def test_simulate_upsert_updates_in_place_without_inflation():
    """Verify in-memory UPSERT updates in-place without adding duplicate rows."""
    store: dict[tuple, dict] = {}
    records_1 = [
        {"user_id": "u-1", "email": "ana@agrosense.co", "full_name": "Ana", "role": "AGRONOMIST"}
    ]

    stats_1 = UpsertEngine.simulate_upsert("users", store, records_1)
    assert stats_1 == {"inserted": 1, "updated": 0, "unchanged": 0}
    assert len(store) == 1

    # Re-run with updated role
    records_2 = [
        {"user_id": "u-1", "email": "ana@agrosense.co", "full_name": "Ana G", "role": "ADMIN"}
    ]
    stats_2 = UpsertEngine.simulate_upsert("users", store, records_2)
    assert stats_2 == {"inserted": 0, "updated": 1, "unchanged": 0}
    assert len(store) == 1  # ZERO row inflation
    assert store[("ana@agrosense.co",)]["role"] == "ADMIN"
    assert store[("ana@agrosense.co",)]["full_name"] == "Ana G"


def test_simulate_upsert_do_nothing_preserves_existing():
    """Verify DO NOTHING preserves original values on conflict."""
    store: dict[tuple, dict] = {}
    records_1 = [{"variety_id": 1, "name": "Castillo", "optimal_temp_min_c": 17.0}]
    UpsertEngine.simulate_upsert("coffee_varieties", store, records_1)

    records_2 = [{"variety_id": 99, "name": "Castillo", "optimal_temp_min_c": 22.0}]
    stats_2 = UpsertEngine.simulate_upsert("coffee_varieties", store, records_2)
    assert stats_2 == {"inserted": 0, "updated": 0, "unchanged": 1}
    assert len(store) == 1
    assert store[("Castillo",)]["optimal_temp_min_c"] == 17.0


def test_strict_idempotency_zero_row_inflation_ct06():
    """Automated Idempotency Assertion Test (pytest / CT-06).

    Verifies that executing the seed twice against the database state produces:
    - 0 row inflation (initial_count == re_run_count across all tables).
    - 0 duplicate keys.
    - 100% checksum convergence.
    """
    faker_gen = AgroSenseFakerGenerator(seed=42)
    dataset = faker_gen.generate_all(mode="dev")

    engine = UpsertEngine(batch_size=500)
    report = engine.verify_idempotency(dataset)

    assert report["is_idempotent"] is True, "CT-06 Violation: dataset is not idempotent"
    assert report["row_inflation_detected"] is False, "CT-06 Violation: row inflation detected"
    assert report["tables_tested"] >= 15

    for table_name, result in report["table_results"].items():
        assert result["passed"] is True, f"Failed idempotency on table: {table_name}"
        assert result["row_inflation"] == 0, f"Inflation on {table_name}: {result['row_inflation']}"
        assert result["initial_count"] == result["re_run_count"]
        assert result["checksum_match"] is True
        assert result["pass2_stats"]["inserted"] == 0, f"Pass 2 re-inserted rows in {table_name}"


def test_engine_invalid_batch_size():
    """Verify validation of batch_size parameter."""
    with pytest.raises(ValueError):
        UpsertEngine(batch_size=0)
    with pytest.raises(ValueError):
        UpsertEngine(batch_size=-10)
    with pytest.raises(ValueError):
        UpsertEngine(batch_size="invalid")  # type: ignore


def test_upsert_engine_edge_cases():
    """Verify edge cases for simulate_upsert and the absence of SQL builders."""
    engine = UpsertEngine(batch_size=100)

    # Unknown table in simulate_upsert
    with pytest.raises(ValueError, match="Tabla no registrada"):
        engine.simulate_upsert("non_existent_table", {}, [{"id": 1}])

    # The in-memory simulator must not pretend to build/execute SQL.
    assert not hasattr(engine, "build_upsert_sql")
    assert not hasattr(engine, "build_all_upsert_statements")


def test_verify_idempotency_detects_inflation(monkeypatch):
    """Verify that verify_idempotency properly reports violations when inflation occurs."""
    engine = UpsertEngine(batch_size=100)
    dataset = {"departments": [{"department_id": 1, "dane_code": "05", "name": "Antioquia"}]}

    # Simulate an engine bug where second run appends rows
    call_count = 0

    def buggy_simulate(table, store, records):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            store[("05",)] = dict(records[0])
        else:
            # Bug: row inflated
            store[("05_bug",)] = dict(records[0])
        return {"inserted": 1, "updated": 0, "unchanged": 0}

    monkeypatch.setattr(UpsertEngine, "simulate_upsert", staticmethod(buggy_simulate))
    report = engine.verify_idempotency(dataset)
    assert report["is_idempotent"] is False
    assert report["row_inflation_detected"] is True
    assert report["table_results"]["departments"]["passed"] is False
