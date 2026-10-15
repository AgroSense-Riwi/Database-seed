"""AgroSense Café — IoT Telemetry Anomaly Generators (DEF-01 & DEF-02).

Implements telemetry time-series generation and specialized anomaly injectors:
- DEF-01: Out-of-order timestamps and lagged packet arrival (RN-01 & CA-01).
- DEF-02: Flatlining sensor readings with variance < 0.5% / STDDEV < 0.005 over 24h (RN-02 & CA-02).
"""

from __future__ import annotations

import copy
import math
import random
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from seed.spatial_models import AGROSENSE_NAMESPACE


def calculate_series_stddev(
    readings: Sequence[dict[str, Any]], field: str = "reading_value"
) -> float:
    """Calculate the sample standard deviation (STDDEV) of a metric field in readings.

    Args:
        readings: List of telemetry dictionaries.
        field: Name of the numerical field to evaluate.

    Returns:
        float: Sample standard deviation (0.0 if fewer than 2 data points).
    """
    values = [float(r[field]) for r in readings if field in r and r[field] is not None]
    n = len(values)
    if n < 2:
        return 0.0
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    return math.sqrt(variance)


def count_out_of_order_inversions(
    readings: Sequence[dict[str, Any]], ts_field: str = "reading_timestamp"
) -> int:
    """Count adjacent temporal inversions where timestamp(i) > timestamp(i+1).

    Args:
        readings: Sequence of telemetry dictionaries.
        ts_field: Key containing ISO-8601 timestamp string.

    Returns:
        int: Number of inversions detected in sequential order.
    """
    inversions = 0
    parsed_timestamps: list[datetime] = []
    for r in readings:
        ts_str = r.get(ts_field)
        if ts_str:
            try:
                parsed_timestamps.append(datetime.fromisoformat(ts_str.replace("Z", "+00:00")))
            except (ValueError, TypeError):
                continue

    for i in range(len(parsed_timestamps) - 1):
        if parsed_timestamps[i] > parsed_timestamps[i + 1]:
            inversions += 1
    return inversions


def generate_sensor_telemetry_series(
    sensor_id: str,
    farm_id: str,
    sensor_type: str = "MULTI_AGRO",
    start_time: str = "2026-10-14T00:00:00Z",
    hours_count: int = 24,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate a realistic nominal chronological time series for an IoT sensor.

    Follows a realistic diurnal cycle for ambient temperature (cool at dawn,
    peak at 14:00) with inversely correlated relative humidity and stable soil moisture.

    Args:
        sensor_id: UUID of the IoT sensor node.
        farm_id: UUID of the farm where the sensor is installed.
        sensor_type: Type of sensor node ('TEMPERATURE', 'SOIL_MOISTURE', 'MULTI_AGRO').
        start_time: ISO-8601 string for first reading.
        hours_count: Total hourly observations to generate (default 24h).
        seed: Random seed for deterministic simulation.

    Returns:
        list[dict[str, Any]]: Chronologically sorted list of nominal telemetry records.
    """
    rng = random.Random(seed)
    base_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    readings: list[dict[str, Any]] = []

    # Nominal baseline parameters for Colombian coffee zone (1400-1800m altitude)
    base_temp = 21.5
    temp_amplitude = 4.5
    base_humidity = 78.0
    soil_moisture_level = round(rng.uniform(32.0, 42.0), 2)
    battery_level = 98.5

    for h in range(hours_count):
        current_dt = base_dt + timedelta(hours=h)
        iso_ts = current_dt.isoformat().replace("+00:00", "Z")

        # Diurnal sinusoidal temperature model (peak at hour 14, trough at hour 5)
        solar_phase = (h % 24 - 9) * (2 * math.pi / 24)
        diurnal_temp = base_temp + temp_amplitude * math.sin(solar_phase)
        temp_val = round(diurnal_temp + rng.uniform(-0.4, 0.4), 2)

        # Humidity is inversely correlated with temperature
        raw_humidity = base_humidity - (temp_val - base_temp) * 3.5 + rng.uniform(-1.0, 1.0)
        humidity_val = round(max(45.0, min(99.0, raw_humidity)), 1)

        # Soil moisture slowly changes
        soil_moisture_level = round(
            max(20.0, min(50.0, soil_moisture_level + rng.uniform(-0.08, 0.05))), 2
        )
        battery_level = round(max(10.0, battery_level - rng.uniform(0.01, 0.04)), 2)

        # Primary scalar reading value depending on sensor type
        if sensor_type == "TEMPERATURE":
            reading_val = temp_val
            unit = "°C"
        elif sensor_type == "SOIL_MOISTURE":
            reading_val = soil_moisture_level
            unit = "%"
        else:
            reading_val = temp_val
            unit = "°C"

        record_key = f"{sensor_id}:{iso_ts}"
        reading_id = str(uuid.uuid5(AGROSENSE_NAMESPACE, record_key))

        readings.append(
            {
                "telemetry_id": reading_id,
                "message_id": reading_id,
                "sensor_id": sensor_id,
                "farm_id": farm_id,
                "sensor_type": sensor_type,
                "device_timestamp_raw": iso_ts,
                "reading_timestamp": iso_ts,
                "server_ingestion_ts": iso_ts,
                "reading_value": reading_val,
                "raw_value": reading_val,
                "raw_unit": unit,
                "temperature": temp_val,
                "humidity": humidity_val,
                "soil_moisture": soil_moisture_level,
                "battery_pct": battery_level,
                "is_out_of_order": False,
                "is_flatlining": False,
            }
        )

    return readings


def inject_out_of_order_anomaly(
    readings: Sequence[dict[str, Any]],
    rate: float = 0.05,
    max_lag_minutes: int = 90,
    seed: int = 42,
    in_place: bool = False,
) -> list[dict[str, Any]]:
    """Inject DEF-01: Out-of-Order timestamps into telemetry stream (RN-01, CA-01).

    Simulates packet arrival delays or transmission jitter. Alters chronological
    order by shifting device timestamps backward or swapping sequential entries,
    verifying Silver-layer sorting and ±15 minute validation slotting.

    Args:
        readings: Sequence of chronological telemetry dictionaries.
        rate: Probability (0.0 to 1.0) of a reading suffering out-of-order delay.
        max_lag_minutes: Maximum minutes to lag an individual packet timestamp.
        seed: PRNG seed for deterministic injection.
        in_place: If False, operates on a deep copy of readings.

    Returns:
        list[dict[str, Any]]: Telemetry stream with out-of-order anomalies injected.
    """
    data = list(readings) if in_place else copy.deepcopy(list(readings))
    n = len(data)
    if n < 2 or rate <= 0.0:
        return data

    rng = random.Random(seed)

    for i in range(1, n):
        if rng.random() < rate:
            orig_ts_str = data[i]["reading_timestamp"]
            try:
                dt = datetime.fromisoformat(orig_ts_str.replace("Z", "+00:00"))
                # Lag the reading timestamp backwards so it arrives out of sequence
                lag_minutes = rng.randint(25, max(30, max_lag_minutes))
                lagged_dt = dt - timedelta(minutes=lag_minutes)
                lagged_ts = lagged_dt.isoformat().replace("+00:00", "Z")

                data[i]["original_timestamp"] = orig_ts_str
                data[i]["reading_timestamp"] = lagged_ts
                data[i]["device_timestamp_raw"] = lagged_ts
                data[i]["is_out_of_order"] = True
                data[i]["anomaly_code"] = "DEF-01"
            except (ValueError, TypeError):
                continue

    # If simple swapping is preferred between adjacent readings:
    for i in range(0, n - 1, 2):
        if rng.random() < (rate * 0.5):
            # Swap adjacent readings' order in the list, simulating network delivery reordering
            data[i], data[i + 1] = data[i + 1], data[i]
            data[i]["is_out_of_order"] = True
            data[i + 1]["is_out_of_order"] = True

    return data


def inject_flatlining_anomaly(
    readings: Sequence[dict[str, Any]],
    rate: float = 0.03,
    max_jitter: float = 0.001,
    seed: int = 42,
    in_place: bool = False,
) -> list[dict[str, Any]]:
    """Inject DEF-02: Flatlining sensor readings (RN-02, CA-02).

    Simulates frozen ADC or hardware lockup where reported physical values
    remain static with variance < 0.5% (STDDEV < 0.005) over 24 continuous hours.
    Downstream anomaly detection queries (STDDEV < 0.005) flag sensor as DEFECTIVE_STUCK.

    Args:
        readings: Sequence of telemetry dictionaries.
        rate: Probability (0.0 to 1.0) of triggering a flatlining failure.
        max_jitter: Maximum noise around static constant (must maintain STDDEV < 0.005).
        seed: PRNG seed for deterministic injection.
        in_place: If False, operates on a deep copy of readings.

    Returns:
        list[dict[str, Any]]: Telemetry stream with flatlining anomaly applied.
    """
    data = list(readings) if in_place else copy.deepcopy(list(readings))
    n = len(data)
    if n < 2 or rate <= 0.0:
        return data

    rng = random.Random(seed)

    # Determine if this series is selected for flatline anomaly
    if rng.random() < rate:
        # Pick frozen static constant value
        frozen_reading = round(rng.uniform(22.0, 24.5), 2)
        frozen_temp = frozen_reading
        frozen_humidity = round(rng.uniform(70.0, 75.0), 2)
        frozen_soil = round(rng.uniform(33.0, 36.0), 2)

        for item in data:
            # Add minuscule jitter ensuring sample STDDEV remains strictly < 0.005
            jitter = rng.uniform(-max_jitter, max_jitter)
            flat_val = round(frozen_reading + jitter, 4)

            item["reading_value"] = flat_val
            item["raw_value"] = flat_val
            item["temperature"] = round(frozen_temp + jitter, 4)
            item["humidity"] = round(frozen_humidity + jitter, 4)
            item["soil_moisture"] = round(frozen_soil + jitter, 4)
            item["is_flatlining"] = True
            item["is_stuck"] = True
            item["anomaly_code"] = "DEF-02"

    return data


def generate_telemetry_dataset(
    sensors: Sequence[dict[str, Any]],
    farms: Sequence[dict[str, Any]] | None = None,
    hours_per_sensor: int = 24,
    out_of_order_rate: float = 0.05,
    flatline_rate: float = 0.03,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Orchestrate generation of complete IoT telemetry dataset with DEF-01 and DEF-02 anomalies.

    Args:
        sensors: List of registered sensor node records (from faker_generators).
        farms: Optional list of farms for metadata mapping.
        hours_per_sensor: Number of hourly readings per sensor (default 24h).
        out_of_order_rate: Effective defect rate for DEF-01 out-of-order timestamps.
        flatline_rate: Effective defect rate for DEF-02 flatlining sensor streams.
        seed: Master PRNG seed.

    Returns:
        list[dict[str, Any]]: Aggregated list of all generated telemetry readings.
    """
    all_readings: list[dict[str, Any]] = []

    for idx, sensor in enumerate(sensors):
        sensor_id = sensor.get("sensor_id", f"S-{idx:04d}")
        farm_id = sensor.get("farm_id", "FARM-DEFAULT")
        sensor_type = sensor.get("type_code", sensor.get("sensor_type", "MULTI_AGRO"))
        sensor_seed = seed + idx * 101

        # 1. Generate nominal chronological time series
        series = generate_sensor_telemetry_series(
            sensor_id=sensor_id,
            farm_id=farm_id,
            sensor_type=sensor_type,
            hours_count=hours_per_sensor,
            seed=sensor_seed,
        )

        # 2. Inject DEF-02: Flatlining Sensor Anomaly
        if flatline_rate > 0.0:
            series = inject_flatlining_anomaly(
                readings=series,
                rate=flatline_rate,
                seed=sensor_seed + 1,
                in_place=True,
            )
            # If flatlined, propagate DEFECTIVE_STUCK status to sensor inventory
            if any(r.get("is_flatlining") for r in series):
                sensor["status"] = "DEFECTIVE_STUCK"
                sensor["health_status"] = "DEFECTIVE_STUCK"

        # 3. Inject DEF-01: Out-of-Order Timestamps
        if out_of_order_rate > 0.0:
            series = inject_out_of_order_anomaly(
                readings=series,
                rate=out_of_order_rate,
                seed=sensor_seed + 2,
                in_place=True,
            )

        all_readings.extend(series)

    return all_readings
