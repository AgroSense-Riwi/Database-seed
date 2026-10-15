"""Unit tests for IoT Telemetry Anomaly Generators (DEF-01 & DEF-02)."""

from datetime import datetime

from seed.telemetry_generators import (
    calculate_series_stddev,
    count_out_of_order_inversions,
    generate_sensor_telemetry_series,
    generate_telemetry_dataset,
    inject_flatlining_anomaly,
    inject_out_of_order_anomaly,
)


def test_nominal_telemetry_series_chronology():
    """Verify nominal telemetry series is generated strictly chronological and valid."""
    readings = generate_sensor_telemetry_series(
        sensor_id="4594fa35-af62-53b6-b2df-ebce3a1eab4c",
        farm_id="7060dc2f-48eb-5db4-9a7d-47ac1b4b4ae9",
        sensor_type="MULTI_AGRO",
        hours_count=24,
        seed=42,
    )

    assert len(readings) == 24
    assert count_out_of_order_inversions(readings) == 0

    # Ensure timestamps strictly increase
    for i in range(len(readings) - 1):
        dt1 = datetime.fromisoformat(readings[i]["reading_timestamp"].replace("Z", "+00:00"))
        dt2 = datetime.fromisoformat(readings[i + 1]["reading_timestamp"].replace("Z", "+00:00"))
        assert dt1 < dt2

    # Physical ranges validation
    for r in readings:
        assert 10.0 <= r["temperature"] <= 35.0
        assert 40.0 <= r["humidity"] <= 100.0
        assert 15.0 <= r["soil_moisture"] <= 60.0
        assert 0.0 <= r["battery_pct"] <= 100.0
        assert r["is_out_of_order"] is False
        assert r["is_flatlining"] is False


def test_stddev_calculation_helper():
    """Verify standard deviation calculation helper behaves mathematically correctly."""
    # Fewer than 2 items
    assert calculate_series_stddev([]) == 0.0
    assert calculate_series_stddev([{"reading_value": 25.0}]) == 0.0

    # Constant items -> stddev = 0
    constant_items = [{"reading_value": 22.0} for _ in range(10)]
    assert calculate_series_stddev(constant_items) == 0.0

    # Known sample
    sample = [
        {"reading_value": 10.0},
        {"reading_value": 12.0},
        {"reading_value": 14.0},
    ]
    # mean = 12, s^2 = ((10-12)^2 + 0 + (14-12)^2) / 2 = 8 / 2 = 4, s = 2.0
    assert abs(calculate_series_stddev(sample) - 2.0) < 1e-6


def test_def01_out_of_order_injection():
    """Verify DEF-01 injects lagged timestamps and causes temporal inversions (RN-01, CA-01)."""
    nominal = generate_sensor_telemetry_series(
        sensor_id="S-001",
        farm_id="F-001",
        hours_count=24,
        seed=42,
    )
    assert count_out_of_order_inversions(nominal) == 0

    # Inject with high probability to guarantee anomalies
    corrupted = inject_out_of_order_anomaly(
        nominal,
        rate=0.5,
        max_lag_minutes=120,
        seed=42,
    )

    inversions = count_out_of_order_inversions(corrupted)
    assert inversions > 0
    assert any(r.get("is_out_of_order") is True for r in corrupted)

    # Zero-rate must preserve chronology completely
    untouched = inject_out_of_order_anomaly(nominal, rate=0.0, seed=42)
    assert count_out_of_order_inversions(untouched) == 0


def test_def02_flatlining_sensor_injection():
    """Verify DEF-02 creates frozen readings with STDDEV < 0.005 over 24h (RN-02, CA-02)."""
    nominal = generate_sensor_telemetry_series(
        sensor_id="S-001",
        farm_id="F-001",
        hours_count=24,
        seed=42,
    )
    # Nominal series has natural diurnal variation (stddev > 1.0)
    nominal_stddev = calculate_series_stddev(nominal, "reading_value")
    assert nominal_stddev > 1.0

    # Inject flatline failure (rate=1.0 forces selection)
    flatlined = inject_flatlining_anomaly(
        nominal,
        rate=1.0,
        max_jitter=0.001,
        seed=42,
    )

    flatline_stddev = calculate_series_stddev(flatlined, "reading_value")
    # Acceptance criterion: standard deviation strictly less than 0.005 (< 0.5% variance)
    assert flatline_stddev < 0.005
    assert all(r.get("is_flatlining") is True for r in flatlined)
    assert all(r.get("is_stuck") is True for r in flatlined)


def test_determinism_in_telemetry_generation():
    """Verify identical PRNG seed yields byte-for-byte identical telemetry streams."""
    run1 = generate_sensor_telemetry_series("S-1", "F-1", seed=99)
    run2 = generate_sensor_telemetry_series("S-1", "F-1", seed=99)
    assert run1 == run2

    anom1 = inject_out_of_order_anomaly(run1, rate=0.3, seed=123)
    anom2 = inject_out_of_order_anomaly(run2, rate=0.3, seed=123)
    assert anom1 == anom2


def test_generate_telemetry_dataset_orchestration():
    """Verify multi-sensor dataset generation and DEFECTIVE_STUCK status propagation (RN-02)."""
    sensors = [
        {
            "sensor_id": f"S-{i:03d}",
            "farm_id": "F-01",
            "status": "ACTIVE",
            "health_status": "ACTIVE",
        }
        for i in range(10)
    ]

    dataset = generate_telemetry_dataset(
        sensors=sensors,
        hours_per_sensor=24,
        out_of_order_rate=0.20,
        flatline_rate=0.30,
        seed=42,
    )

    # 10 sensors * 24 hours = 240 readings
    assert len(dataset) == 240

    # Verify out-of-order anomalies injected
    out_of_order_count = sum(1 for r in dataset if r.get("is_out_of_order"))
    assert out_of_order_count > 0

    # Verify flatlining anomalies injected
    flatline_count = sum(1 for r in dataset if r.get("is_flatlining"))
    assert flatline_count > 0

    # Verify sensor status propagated to DEFECTIVE_STUCK for affected sensors
    stuck_sensors = [s for s in sensors if s["status"] == "DEFECTIVE_STUCK"]
    assert len(stuck_sensors) > 0
    assert all(s["health_status"] == "DEFECTIVE_STUCK" for s in stuck_sensors)
