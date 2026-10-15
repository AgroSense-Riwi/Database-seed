"""Pytest Automated Verification Suite for Injected Anomaly Frequencies.

Certifies that anomaly injection frequencies across all defect codes (DEF-01 through DEF-07),
spatial generators, and telemetry streams match the target --defect-rate CLI parameter
in accordance with Deliverable E-03, CT-06, and Docusaurus Quality Criteria Matrix.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from seed.defect_factory import (
    DEFAULT_BASE_DEFECT_RATES,
    DefectFactory,
)
from seed.faker_generators import AgroSenseFakerGenerator
from seed.run_seed import get_last_defect_report, run_seed
from seed.spatial import PostGISSpatialGenerator, SpatialOverlapGenerator
from seed.telemetry_generators import (
    generate_sensor_telemetry_series,
    generate_telemetry_dataset,
    inject_out_of_order_anomaly,
)


@pytest.fixture(scope="module")
def deterministic_dataset() -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic dataset once for frequency verification."""
    gen = AgroSenseFakerGenerator(seed=42)
    return gen.generate_all(mode="dev")


def test_zero_defect_rate_frequency_is_strictly_zero(
    deterministic_dataset: dict[str, list[dict[str, Any]]],
) -> None:
    """Verify that --defect-rate=0.0 injects strictly 0 anomalies across all entities."""
    factory = DefectFactory(defect_rate=0.0, seed=42)
    mutated = factory.apply(deterministic_dataset)

    summary = factory.get_summary()
    assert summary["global_defect_rate"] == 0.0
    assert summary["total_defects_injected"] == 0
    assert factory.report.total_injected == 0
    assert len(factory.report.injections) == 0
    assert factory.report.counts_by_code == {}

    # Verify no entity fields were mutated by DefectFactory
    assert all(f.get("has_valid_coords") is True for f in mutated.get("farms", []))
    assert all(s.get("clock_drift_seconds") == 0 for s in mutated.get("iot_sensors", []))
    assert all(s.get("status") == "ACTIVE" for s in mutated.get("iot_sensors", []))
    assert all(d.get("farm_id") is not None for d in mutated.get("harvest_deliveries", []))


def test_effective_defect_rate_proportional_formula() -> None:
    """Verify calculate_effective_rate scales proportionally relative to nominal 0.05 base."""
    factory_nominal = DefectFactory(defect_rate=0.05, seed=42)
    for code, base_rate in DEFAULT_BASE_DEFECT_RATES.items():
        assert math.isclose(factory_nominal.calculate_effective_rate(code), base_rate, rel_tol=1e-5)

    # Double rate (0.10) -> exactly double base rate
    factory_double = DefectFactory(defect_rate=0.10, seed=42)
    for code, base_rate in DEFAULT_BASE_DEFECT_RATES.items():
        expected = min(1.0, base_rate * 2.0)
        assert math.isclose(factory_double.calculate_effective_rate(code), expected, rel_tol=1e-5)

    # Zero rate -> strictly 0.0
    factory_zero = DefectFactory(defect_rate=0.0, seed=42)
    for code in DEFAULT_BASE_DEFECT_RATES:
        assert factory_zero.calculate_effective_rate(code) == 0.0

    # Saturation rate (1.0) -> strictly 1.0
    factory_max = DefectFactory(defect_rate=1.0, seed=42)
    for code in DEFAULT_BASE_DEFECT_RATES:
        assert factory_max.calculate_effective_rate(code) == 1.0


def test_defect_frequency_monotonic_scaling(
    deterministic_dataset: dict[str, list[dict[str, Any]]],
) -> None:
    """Verify that increasing --defect-rate monotonically increases or preserves injected count."""
    rates = [0.0, 0.02, 0.05, 0.10, 0.25, 0.50, 1.0]
    injected_counts: list[int] = []

    for r in rates:
        factory = DefectFactory(defect_rate=r, seed=42)
        factory.apply(deterministic_dataset)
        injected_counts.append(factory.report.total_injected)

    # Assert non-decreasing monotonic progression
    for i in range(len(injected_counts) - 1):
        assert injected_counts[i] <= injected_counts[i + 1], (
            f"Non-monotonic progression at index {i}: "
            f"rate {rates[i]} produced {injected_counts[i]}, but "
            f"rate {rates[i + 1]} produced {injected_counts[i + 1]}"
        )


def test_saturation_defect_rate_mutates_all_candidates(
    deterministic_dataset: dict[str, list[dict[str, Any]]],
) -> None:
    """Verify that --defect-rate=1.0 injects defects into 100% of candidate entities."""
    factory = DefectFactory(defect_rate=1.0, seed=42)
    mutated = factory.apply(deterministic_dataset)

    # DEF-01: All sensors have clock drift
    assert all(s.get("clock_drift_seconds") != 0 for s in mutated["iot_sensors"])

    # DEF-02: All sensors are marked DEFECTIVE_STUCK
    assert all(s.get("status") == "DEFECTIVE_STUCK" for s in mutated["iot_sensors"])

    # DEF-03: All sensors have delayed block days
    assert all("delayed_block_days" in s for s in mutated["iot_sensors"])

    # DEF-04: All farms have coordinates invalidated
    assert all(f.get("has_valid_coords") is False for f in mutated["farms"])

    # DEF-06: All harvest deliveries have unlinked farm_id
    assert all(d.get("farm_id") is None for d in mutated["harvest_deliveries"])

    # DEF-07: All farms are marked as overlapping reserve
    assert all(f.get("overlaps_reserve") is True for f in mutated["farms"])


def test_telemetry_out_of_order_frequency_bounds() -> None:
    """Verify DEF-01 out-of-order injection frequency aligns with target rate parameter."""
    series = generate_sensor_telemetry_series(
        sensor_id="S-FREQ-01",
        farm_id="F-FREQ-01",
        hours_count=200,
        seed=42,
    )

    # Zero rate must yield zero anomalies
    nominal = inject_out_of_order_anomaly(series, rate=0.0, seed=42)
    assert sum(1 for r in nominal if r.get("is_out_of_order")) == 0

    # 25% target rate over 200 readings -> expected ~50 DEF-01 lagged anomalies
    target_rate = 0.25
    corrupted = inject_out_of_order_anomaly(series, rate=target_rate, seed=42)
    def01_lagged_count = sum(1 for r in corrupted if r.get("anomaly_code") == "DEF-01")
    observed_rate = def01_lagged_count / len(series)

    # Tolerance window of +/- 8% around target rate for random sample
    assert abs(observed_rate - target_rate) < 0.08

    # Total out of order (lagged + swapped) must be strictly greater than or equal to lagged
    total_out_of_order = sum(1 for r in corrupted if r.get("is_out_of_order"))
    assert total_out_of_order >= def01_lagged_count


def test_telemetry_dataset_flatline_frequency_bounds() -> None:
    """Verify DEF-02 flatline sensor defect frequency reflects target flatline_rate parameter."""
    sensor_count = 50
    sensors = [
        {"sensor_id": f"S-{i:03d}", "farm_id": "F-01", "status": "ACTIVE"}
        for i in range(sensor_count)
    ]

    target_flatline_rate = 0.20  # 20% flatline rate -> ~10 sensors
    dataset = generate_telemetry_dataset(
        sensors=sensors,
        hours_per_sensor=24,
        out_of_order_rate=0.0,
        flatline_rate=target_flatline_rate,
        seed=42,
    )

    stuck_sensors = [s for s in sensors if s.get("status") == "DEFECTIVE_STUCK"]
    observed_rate = len(stuck_sensors) / sensor_count

    # Check observed rate is within reasonable binomial bounds [0.08, 0.35]
    assert 0.08 <= observed_rate <= 0.35
    # Verify flatline telemetry readings were generated
    flatline_readings = [r for r in dataset if r.get("is_flatlining")]
    assert len(flatline_readings) == len(stuck_sensors) * 24


def test_spatial_overlap_frequency_matches_target_rate() -> None:
    """Verify spatial overlap generator respects the overlap_rate parameter."""
    spatial = PostGISSpatialGenerator(seed=42)
    overlap_gen = SpatialOverlapGenerator(seed=42)

    raw_reserves = spatial.generate_forest_reserves(count=3)
    reserves_data = [
        {
            "reserve_id": r.entity_id,
            "reserve_code": r.entity_code,
            "geom_ewkt": r.ewkt,
            "polygon_geojson": r.geojson,
            "area_ha": r.area_ha,
        }
        for r in raw_reserves
    ]

    farm_count = 40
    farms = [
        {
            "farm_id": f"f-{i}",
            "farm_code": f"FIN-{i:04d}",
            "name": f"Finca {i}",
            "total_area_ha": 12.0,
            "overlaps_reserve": False,
        }
        for i in range(farm_count)
    ]

    target_rate = 0.25  # 25% target overlap rate -> ~10 farms
    overlaps = overlap_gen.generate_overlaps_for_dataset(
        farms=farms,
        reserves=reserves_data,
        overlap_rate=target_rate,
    )

    observed_rate = len(overlaps) / farm_count
    # Binomial margin of error for n=40: [0.10, 0.40]
    assert 0.10 <= observed_rate <= 0.40
    assert len([f for f in farms if f.get("overlaps_reserve")]) == len(overlaps)


def test_cli_defect_rate_integration_and_report_metadata() -> None:
    """Verify run_seed execution records exact --defect-rate parameter in report metadata."""
    target_rate = 0.12
    exit_code = run_seed(seed_value=42, mode="dev", defect_rate=target_rate)
    assert exit_code == 0

    report = get_last_defect_report()
    assert report is not None
    assert math.isclose(report.global_defect_rate, target_rate, rel_tol=1e-5)
    assert report.total_injected > 0

    # Ensure affected tables metric is correctly tracked
    summary = report.get_summary()
    assert summary["global_defect_rate"] == target_rate
    assert "affected_tables" in summary
    assert len(summary["affected_tables"]) > 0
