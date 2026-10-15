"""Unit and integration tests for DefectFactory anomaly injection (AGRO-05C)."""

import pytest

from seed.defect_factory import (
    DEFAULT_BASE_DEFECT_RATES,
    DefectFactory,
    DefectReport,
    InjectedDefectRecord,
)
from seed.faker_generators import AgroSenseFakerGenerator
from seed.run_seed import get_last_defect_report, run_seed


@pytest.fixture
def sample_dataset():
    """Generate a clean deterministic dev dataset for defect testing."""
    gen = AgroSenseFakerGenerator(seed=42)
    return gen.generate_all(mode="dev")


def test_defect_factory_invalid_rate():
    """Verify that defect_rate outside [0.0, 1.0] raises ValueError."""
    with pytest.raises(ValueError, match="defect_rate must be between 0.0 and 1.0"):
        DefectFactory(defect_rate=-0.01)

    with pytest.raises(ValueError, match="defect_rate must be between 0.0 and 1.0"):
        DefectFactory(defect_rate=1.01)


def test_zero_defect_mode(sample_dataset):
    """Verify that defect_rate=0.0 produces zero defects (baseline testing)."""
    factory = DefectFactory(defect_rate=0.0, seed=42)
    mutated = factory.apply(sample_dataset)

    summary = factory.get_summary()
    assert summary["total_defects_injected"] == 0
    assert summary["global_defect_rate"] == 0.0
    assert factory.report.total_injected == 0

    # Ensure farms retain valid coordinates and normal sensors
    assert all(f.get("has_valid_coords") is True for f in mutated["farms"])
    assert all(s.get("clock_drift_seconds") == 0 for s in mutated["iot_sensors"])
    assert all(s.get("status") == "ACTIVE" for s in mutated["iot_sensors"])


def test_determinism_across_runs(sample_dataset):
    """Verify identical PRNG seed produces exact same defects across runs."""
    factory1 = DefectFactory(defect_rate=0.10, seed=42)
    mutated1 = factory1.apply(sample_dataset)

    factory2 = DefectFactory(defect_rate=0.10, seed=42)
    mutated2 = factory2.apply(sample_dataset)

    assert factory1.report.total_injected == factory2.report.total_injected
    assert factory1.report.counts_by_code == factory2.report.counts_by_code

    # Check that identical records were modified
    injections1 = [(i.defect_code, i.entity_id, i.field_modified) for i in factory1.report.injections]
    injections2 = [(i.defect_code, i.entity_id, i.field_modified) for i in factory2.report.injections]
    assert injections1 == injections2


def test_def01_clock_drift_injection(sample_dataset):
    """Verify DEF-01 injects non-zero clock drift into iot_sensors."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-01"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-01", 0) > 0
    drifted_sensors = [s for s in mutated["iot_sensors"] if s.get("clock_drift_seconds") != 0]
    assert len(drifted_sensors) == len(mutated["iot_sensors"])
    for s in drifted_sensors:
        # Offset must be between -7200 and +43200 seconds (-2h to +12h)
        assert -7200 <= s["clock_drift_seconds"] <= 43200


def test_def02_stuck_sensor_injection(sample_dataset):
    """Verify DEF-02 flags sensors as DEFECTIVE_STUCK."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-02"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-02", 0) > 0
    stuck_sensors = [s for s in mutated["iot_sensors"] if s.get("status") == "DEFECTIVE_STUCK"]
    assert len(stuck_sensors) == len(mutated["iot_sensors"])
    for s in stuck_sensors:
        assert s["health_status"] == "DEFECTIVE_STUCK"


def test_def03_delayed_blocks_injection(sample_dataset):
    """Verify DEF-03 delays last transmission by 1-7 days."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-03"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-03", 0) > 0
    delayed = [s for s in mutated["iot_sensors"] if "delayed_block_days" in s]
    assert len(delayed) == len(mutated["iot_sensors"])
    for s in delayed:
        assert 1 <= s["delayed_block_days"] <= 7


def test_def04_bad_coordinates_injection(sample_dataset):
    """Verify DEF-04 flags farms with has_valid_coords=False."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-04"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-04", 0) > 0
    invalid_farms = [f for f in mutated["farms"] if f.get("has_valid_coords") is False]
    assert len(invalid_farms) == len(mutated["farms"])


def test_def05_mixed_soil_units_injection(sample_dataset):
    """Verify DEF-05 alternates reporting units between ppm, mg/kg, %, and g/kg."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-05"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-05", 0) > 0
    units = {a.get("raw_unit_reported") for a in mutated["soil_lab_analyses"]}
    assert units.issubset({"ppm", "mg/kg", "%", "g/kg"})
    assert len(units) > 1


def test_def06_unlinked_deliveries_injection(sample_dataset):
    """Verify DEF-06 unlinks deliveries and invalidates export batches (is_exportable=False)."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-06"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-06", 0) > 0
    unlinked = [d for d in mutated["harvest_deliveries"] if d.get("farm_id") is None]
    assert len(unlinked) == len(mutated["harvest_deliveries"])

    quarantined_batches = [b for b in mutated["export_batches"] if b.get("is_exportable") is False]
    assert len(quarantined_batches) > 0


def test_def07_reserve_overlap_injection(sample_dataset):
    """Verify DEF-07 flags forest reserve overlap and revokes certification."""
    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-07"})
    mutated = factory.apply(sample_dataset)

    assert factory.report.counts_by_code.get("DEF-07", 0) > 0
    overlapping = [f for f in mutated["farms"] if f.get("overlaps_reserve") is True]
    assert len(overlapping) == len(mutated["farms"])


def test_telemetries_injection_support():
    """Verify DefectFactory also injects anomalies when iot_telemetries exist."""
    telemetries = [
        {"telemetry_id": "TEL-1", "sensor_id": "S-1", "reading_timestamp": "2026-10-15T10:00:00Z"},
        {"telemetry_id": "TEL-2", "sensor_id": "S-2", "reading_timestamp": "2026-10-15T10:00:00Z"},
    ]
    sensors = [
        {"sensor_id": "S-1", "status": "ACTIVE", "health_status": "ACTIVE", "clock_drift_seconds": 0},
        {"sensor_id": "S-2", "status": "ACTIVE", "health_status": "ACTIVE", "clock_drift_seconds": 0},
    ]
    dataset = {"iot_telemetries": telemetries, "iot_sensors": sensors}

    factory = DefectFactory(defect_rate=1.0, seed=42, enabled_defects={"DEF-01", "DEF-02", "DEF-03"})
    mutated = factory.apply(dataset)

    # Telemetries timestamps adjusted and delayed batch added
    assert any(t.get("reading_timestamp") != "2026-10-15T10:00:00Z" for t in mutated["iot_telemetries"])
    assert any("ingestion_batch_id" in t for t in mutated["iot_telemetries"])


def test_run_seed_integration_with_defect_factory():
    """Verify end-to-end execution of run_seed injects defects and populates report."""
    exit_code = run_seed(seed_value=42, mode="dev", defect_rate=0.15)
    assert exit_code == 0

    report = get_last_defect_report()
    assert report is not None
    assert report.global_defect_rate == 0.15
    assert report.total_injected > 0
    assert "DEF-01" in report.counts_by_code or "DEF-05" in report.counts_by_code
