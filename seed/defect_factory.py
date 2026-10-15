"""AgroSense Café — Configurable Data Quality Defect Injection Engine (AGRO-05C).

Provides deterministic and configurable anomaly injection across synthetic datasets
governed by the --defect-rate parameter (SEED_DEFECT_GLOBAL_RATE). Simulates real-world
data quality defects (DEF-01 through DEF-06/07) to validate downstream ETL pipelines,
business rules enforcement (RN-01 through RN-09), and automated alert triggers.
"""

from __future__ import annotations

import copy
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("agrosense.seed.defect_factory")

# Base defect rates defined in Data Quality Defects Catalog & Injection Matrix (v2)
DEFAULT_BASE_DEFECT_RATES: dict[str, float] = {
    "DEF-01": 0.05,  # Clock Drift (iot_sensors / iot_telemetries)
    "DEF-02": 0.03,  # Stuck Sensor Anomaly (iot_sensors / iot_telemetries)
    "DEF-03": 0.10,  # Delayed IoT Blocks (telemetry batches / transmissions)
    "DEF-04": 0.02,  # Bad Coordinates (farms)
    "DEF-05": 0.15,  # Mixed Soil Units (soil_lab_analyses)
    "DEF-06": 0.02,  # Unlinked Deliveries (harvest_deliveries / export_batches)
    "DEF-07": 0.05,  # Forest Reserve Overlap (farm_reserve_overlaps / export_batches)
}


@dataclass
class InjectedDefectRecord:
    """Record of an individual defect injected into a dataset entity."""

    defect_code: str
    defect_name: str
    target_table: str
    entity_id: str
    field_modified: str
    original_value: Any
    mutated_value: Any
    business_rule: str


@dataclass
class DefectReport:
    """Comprehensive summary of all defects injected during execution."""

    global_defect_rate: float
    total_injected: int = 0
    counts_by_code: dict[str, int] = field(default_factory=dict)
    affected_tables: dict[str, int] = field(default_factory=dict)
    injections: list[InjectedDefectRecord] = field(default_factory=list)

    def get_summary(self) -> dict[str, Any]:
        """Return high-level defect injection metrics."""
        return {
            "global_defect_rate": self.global_defect_rate,
            "total_defects_injected": self.total_injected,
            "defects_by_code": dict(self.counts_by_code),
            "affected_tables": dict(self.affected_tables),
        }


class DefectFactory:
    """Configurable pipeline module for controlled data quality defect injection.

    Attributes:
        defect_rate: Global defect multiplier between 0.0 and 1.0.
        seed: PRNG seed for deterministic and reproducible injection.
        enabled_defects: Set of defect codes to consider. Defaults to all DEF codes.
    """

    def __init__(
        self,
        defect_rate: float = 0.05,
        seed: int = 42,
        custom_rates: dict[str, float] | None = None,
        enabled_defects: set[str] | None = None,
    ) -> None:
        if not 0.0 <= defect_rate <= 1.0:
            raise ValueError(f"defect_rate must be between 0.0 and 1.0, got: {defect_rate}")

        self.defect_rate = float(defect_rate)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.base_rates = dict(DEFAULT_BASE_DEFECT_RATES)
        if custom_rates:
            self.base_rates.update(custom_rates)

        self.enabled_defects = (
            set(enabled_defects)
            if enabled_defects is not None
            else set(self.base_rates.keys())
        )
        self.report = DefectReport(global_defect_rate=self.defect_rate)

    def calculate_effective_rate(self, defect_code: str) -> float:
        """Calculate effective probability of injection for a defect code.

        When global defect_rate is 0.0, effective rate is strictly 0.0.
        Otherwise, scales proportionally based on catalog base rate.
        """
        if self.defect_rate <= 0.0 or defect_code not in self.enabled_defects:
            return 0.0
        if self.defect_rate >= 1.0:
            return 1.0

        base_rate = self.base_rates.get(defect_code, 0.05)
        # Scaled proportionally relative to nominal 0.05 base
        scale_factor = self.defect_rate / 0.05
        effective_rate = min(1.0, base_rate * scale_factor)
        return effective_rate

    def _should_inject(self, defect_code: str) -> bool:
        """Deterministic Bernoulli trial based on effective defect rate."""
        effective_rate = self.calculate_effective_rate(defect_code)
        if effective_rate <= 0.0:
            return False
        if effective_rate >= 1.0:
            return True
        return self.rng.random() < effective_rate

    def _record_injection(
        self,
        code: str,
        name: str,
        table: str,
        entity_id: str,
        field_modified: str,
        original_value: Any,
        mutated_value: Any,
        rule: str,
    ) -> None:
        """Register defect into the report tracker."""
        self.report.total_injected += 1
        self.report.counts_by_code[code] = self.report.counts_by_code.get(code, 0) + 1
        self.report.affected_tables[table] = self.report.affected_tables.get(table, 0) + 1
        self.report.injections.append(
            InjectedDefectRecord(
                defect_code=code,
                defect_name=name,
                target_table=table,
                entity_id=str(entity_id),
                field_modified=field_modified,
                original_value=original_value,
                mutated_value=mutated_value,
                business_rule=rule,
            )
        )

    def apply(
        self,
        dataset: dict[str, list[dict[str, Any]]],
        in_place: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        """Inject configured defects across target entities in the dataset.

        Args:
            dataset: Dictionary mapping table names to entity record lists.
            in_place: If False, operates on a deep copy of dataset.

        Returns:
            dict[str, list[dict[str, Any]]]: Dataset with anomalies injected.
        """
        data = dataset if in_place else copy.deepcopy(dataset)

        if self.defect_rate <= 0.0:
            logger.debug("Zero-defect mode active (defect_rate=0.0). Skipping injection.")
            return data

        logger.info(
            "Applying DefectFactory injection with global rate=%.3f, seed=%d",
            self.defect_rate,
            self.seed,
        )

        # 1. DEF-04: Bad Coordinates & Geometries (farms)
        self.inject_def04_bad_coordinates(data.get("farms", []))

        # 2. DEF-01: Clock Drift (iot_sensors / iot_telemetries)
        self.inject_def01_clock_drift(
            sensors=data.get("iot_sensors", []),
            telemetries=data.get("iot_telemetries", []),
        )

        # 3. DEF-02: Stuck / Frozen Sensor Stream (iot_sensors / iot_telemetries)
        self.inject_def02_stuck_sensors(
            sensors=data.get("iot_sensors", []),
            telemetries=data.get("iot_telemetries", []),
        )

        # 4. DEF-03: Delayed IoT Blocks (iot_telemetries / iot_sensors)
        self.inject_def03_delayed_blocks(
            telemetries=data.get("iot_telemetries", []),
            sensors=data.get("iot_sensors", []),
        )

        # 5. DEF-05: Mixed Soil Laboratory Units (soil_lab_analyses)
        self.inject_def05_mixed_soil_units(data.get("soil_lab_analyses", []))

        # 6. DEF-06: Unlinked Harvest Deliveries (harvest_deliveries & export_batches)
        self.inject_def06_unlinked_deliveries(
            deliveries=data.get("harvest_deliveries", []),
            export_batches=data.get("export_batches", []),
            compositions=data.get("batch_farm_compositions", []),
        )

        # 7. DEF-07: Forest Reserve Overlaps (farm_reserve_overlaps / export_batches)
        self.inject_def07_reserve_overlaps(
            farms=data.get("farms", []),
            export_batches=data.get("export_batches", []),
        )

        logger.info(
            "DefectFactory complete. Total injected: %d. By code: %s",
            self.report.total_injected,
            self.report.counts_by_code,
        )
        return data

    def inject_def01_clock_drift(
        self,
        sensors: list[dict[str, Any]],
        telemetries: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject DEF-01: Clock Drift (-2 hours to +12 hours).

        Simulates desynchronized MCU internal clock. Targets iot_sensors
        (clock_drift_seconds) and iot_telemetries (reading_timestamp).
        Evaluates RN-01 and CA-01 (±15 minute validation window).
        """
        code = "DEF-01"
        name = "Clock Drift"
        rule = "RN-01 & CA-01 (±15 min timestamp correction window)"

        for sensor in sensors:
            if self._should_inject(code):
                # Drift between -2h (-7200s) and +12h (+43200s), avoiding 0
                offset_hours = self.rng.choice([-2.0, -1.5, -0.75, 1.0, 2.5, 4.0, 8.0, 12.0])
                offset_seconds = int(offset_hours * 3600)
                orig = sensor.get("clock_drift_seconds", 0)
                sensor["clock_drift_seconds"] = offset_seconds

                self._record_injection(
                    code=code,
                    name=name,
                    table="iot_sensors",
                    entity_id=sensor.get("sensor_id", sensor.get("serial_number", "unknown")),
                    field_modified="clock_drift_seconds",
                    original_value=orig,
                    mutated_value=offset_seconds,
                    rule=rule,
                )

        if telemetries:
            for item in telemetries:
                if self._should_inject(code):
                    orig_ts = item.get("reading_timestamp")
                    if orig_ts:
                        try:
                            # Apply offset to ISO timestamp string
                            dt = datetime.fromisoformat(orig_ts.replace("Z", "+00:00"))
                            offset = timedelta(hours=self.rng.choice([-3, -2, 4, 8, 12]))
                            new_ts = (dt + offset).isoformat().replace("+00:00", "Z")
                            item["reading_timestamp"] = new_ts
                            self._record_injection(
                                code=code,
                                name=name,
                                table="iot_telemetries",
                                entity_id=item.get("telemetry_id", item.get("sensor_id", "item")),
                                field_modified="reading_timestamp",
                                original_value=orig_ts,
                                mutated_value=new_ts,
                                rule=rule,
                            )
                        except Exception:
                            pass

    def inject_def02_stuck_sensors(
        self,
        sensors: list[dict[str, Any]],
        telemetries: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject DEF-02: Stuck Sensor Anomaly (<0.5% variance over 24h).

        Flags sensor as DEFECTIVE_STUCK and suppresses alerts (RN-02, CA-02).
        """
        code = "DEF-02"
        name = "Stuck Sensor Anomaly"
        rule = "RN-02 & CA-02 (Flag DEFECTIVE_STUCK and exclude from alert engines)"

        for sensor in sensors:
            if self._should_inject(code):
                orig_status = sensor.get("status")
                sensor["status"] = "DEFECTIVE_STUCK"
                sensor["health_status"] = "DEFECTIVE_STUCK"

                self._record_injection(
                    code=code,
                    name=name,
                    table="iot_sensors",
                    entity_id=sensor.get("sensor_id", sensor.get("serial_number", "unknown")),
                    field_modified="status",
                    original_value=orig_status,
                    mutated_value="DEFECTIVE_STUCK",
                    rule=rule,
                )

        if telemetries:
            # Flatten readings for defective sensors
            stuck_sensor_ids = {
                s.get("sensor_id") for s in sensors if s.get("status") == "DEFECTIVE_STUCK"
            }
            for item in telemetries:
                if item.get("sensor_id") in stuck_sensor_ids:
                    # Freeze value to static constant
                    item["reading_value"] = round(self.rng.uniform(22.0, 22.1), 2)
                    item["is_stuck"] = True

    def inject_def03_delayed_blocks(
        self,
        telemetries: list[dict[str, Any]] | None = None,
        sensors: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject DEF-03: Delayed IoT Blocks (1 to 7 days transmission delay).

        Simulates cellular outage / connectivity outage in rural areas (RNF-01, CA-01).
        """
        code = "DEF-03"
        name = "Delayed IoT Blocks"
        rule = "CA-01 & RNF-01 (Bulk delayed ingestion without duplicates)"

        if sensors:
            for sensor in sensors:
                if self._should_inject(code):
                    delayed_days = self.rng.randint(1, 7)
                    orig_tx = sensor.get("last_transmission_at")
                    if orig_tx:
                        try:
                            dt = datetime.fromisoformat(orig_tx.replace("Z", "+00:00"))
                            new_tx = (dt - timedelta(days=delayed_days)).isoformat().replace("+00:00", "Z")
                            sensor["last_transmission_at"] = new_tx
                            sensor["delayed_block_days"] = delayed_days

                            self._record_injection(
                                code=code,
                                name=name,
                                table="iot_sensors",
                                entity_id=sensor.get("sensor_id", sensor.get("serial_number", "s")),
                                field_modified="last_transmission_at",
                                original_value=orig_tx,
                                mutated_value=new_tx,
                                rule=rule,
                            )
                        except Exception:
                            pass

        if telemetries:
            for item in telemetries:
                if self._should_inject(code):
                    item["ingestion_batch_id"] = f"DELAYED_BATCH_{self.rng.randint(100, 999)}"
                    item["transmission_delay_hours"] = self.rng.randint(24, 168)

    def inject_def04_bad_coordinates(self, farms: list[dict[str, Any]]) -> None:
        """Inject DEF-04: Bad Geographic Coordinates.

        Generates coordinates clearly outside Colombia coffee zones or swapped lat/long,
        and sets has_valid_coords = False.
        """
        code = "DEF-04"
        name = "Bad Geographic Coordinates"
        rule = "Spatial Validation (ST_Contains bounding box sanity check)"

        for farm in farms:
            if self._should_inject(code):
                orig_coords = (farm.get("latitude"), farm.get("longitude"))
                strategy = self.rng.choice(["out_of_bounds", "swap"])

                if strategy == "out_of_bounds":
                    # Coordinates in Mediterranean or Northern Europe
                    new_lat = round(self.rng.uniform(36.0, 48.0), 6)
                    new_lon = round(self.rng.uniform(10.0, 25.0), 6)
                else:
                    # Inverted latitude and longitude
                    new_lat = farm.get("longitude", -75.5)
                    new_lon = farm.get("latitude", 4.5)

                farm["latitude"] = new_lat
                farm["longitude"] = new_lon
                farm["has_valid_coords"] = False

                self._record_injection(
                    code=code,
                    name=name,
                    table="farms",
                    entity_id=farm.get("farm_id", farm.get("farm_code", "farm")),
                    field_modified="latitude,longitude",
                    original_value=orig_coords,
                    mutated_value=(new_lat, new_lon),
                    rule=rule,
                )

    def inject_def05_mixed_soil_units(self, analyses: list[dict[str, Any]]) -> None:
        """Inject DEF-05: Mixed Soil Laboratory Units.

        Alternates reporting units between ppm, mg/kg, %, and g/kg.
        Validates Silver layer unit normalizer to mg/kg (RN-07, CA-06).
        """
        code = "DEF-05"
        name = "Mixed Soil Laboratory Units"
        rule = "RN-07 & CA-06 (Mandatory unit standardization to mg/kg)"

        alternate_units = ["ppm", "mg/kg", "%", "g/kg"]

        for analysis in analyses:
            if self._should_inject(code):
                orig_unit = analysis.get("raw_unit_reported", "ppm")
                chosen_unit = self.rng.choice(alternate_units)
                analysis["raw_unit_reported"] = chosen_unit

                # Invert or rescale nitrogen or phosphorus according to unit
                if chosen_unit == "%":
                    analysis["nitrogen_ppm"] = round(analysis.get("nitrogen_ppm", 50.0) / 10000.0, 5)
                elif chosen_unit == "g/kg":
                    analysis["nitrogen_ppm"] = round(analysis.get("nitrogen_ppm", 50.0) / 1000.0, 4)

                self._record_injection(
                    code=code,
                    name=name,
                    table="soil_lab_analyses",
                    entity_id=analysis.get("analysis_id", "analysis"),
                    field_modified="raw_unit_reported",
                    original_value=orig_unit,
                    mutated_value=chosen_unit,
                    rule=rule,
                )

    def inject_def06_unlinked_deliveries(
        self,
        deliveries: list[dict[str, Any]],
        export_batches: list[dict[str, Any]] | None = None,
        compositions: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject DEF-06: Unlinked Harvest Deliveries (farm_id = None or invalid).

        Invalidates downstream export batch traceability: is_exportable = False (RN-08, CA-07).
        """
        code = "DEF-06"
        name = "Unlinked Harvest Deliveries"
        rule = "RN-08 & CA-07 (Revoke export eligibility: is_exportable = FALSE)"

        affected_delivery_ids: set[str] = set()

        for delivery in deliveries:
            if self._should_inject(code):
                orig_farm = delivery.get("farm_id")
                # Nullify farm link
                delivery["farm_id"] = None
                delivery_id = str(delivery.get("delivery_id", ""))
                affected_delivery_ids.add(delivery_id)

                self._record_injection(
                    code=code,
                    name=name,
                    table="harvest_deliveries",
                    entity_id=delivery_id,
                    field_modified="farm_id",
                    original_value=orig_farm,
                    mutated_value=None,
                    rule=rule,
                )

        # Invalidate related export batches if affected delivery is part of batch composition
        if export_batches and affected_delivery_ids:
            for batch in export_batches:
                batch_code = batch.get("batch_code", "")
                if compositions:
                    # Check if any affected delivery is in this batch
                    is_affected = any(
                        (c.get("batch_id") == batch.get("batch_id") or c.get("batch_code") == batch_code)
                        and c.get("delivery_id") in affected_delivery_ids
                        for c in compositions
                    )
                else:
                    is_affected = self.rng.random() < 0.20

                if is_affected:
                    orig_exportable = batch.get("is_exportable", True)
                    batch["is_exportable"] = False
                    batch["traceability_status"] = "QUARANTINED_UNLINKED_DELIVERY"
                    self._record_injection(
                        code=code,
                        name=name,
                        table="export_batches",
                        entity_id=batch_code,
                        field_modified="is_exportable",
                        original_value=orig_exportable,
                        mutated_value=False,
                        rule=rule,
                    )

    def inject_def07_reserve_overlaps(
        self,
        farms: list[dict[str, Any]],
        export_batches: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject DEF-07: Forest Reserve Overlap.

        Flags farm overlap and revokes sustainability certification (RN-09, CA-08).
        """
        code = "DEF-07"
        name = "Forest Reserve Overlap"
        rule = "RN-09 & CA-08 (Revoke certification: is_certified = FALSE)"

        overlapping_farm_ids: set[str] = set()

        for farm in farms:
            if self._should_inject(code):
                farm["overlaps_reserve"] = True
                farm_id = str(farm.get("farm_id", ""))
                overlapping_farm_ids.add(farm_id)

                self._record_injection(
                    code=code,
                    name=name,
                    table="farms",
                    entity_id=farm_id,
                    field_modified="overlaps_reserve",
                    original_value=False,
                    mutated_value=True,
                    rule=rule,
                )

        if export_batches and overlapping_farm_ids:
            # If batch has overlapping farms, revoke certification
            for batch in export_batches:
                if self.rng.random() < 0.15:
                    orig_cert = batch.get("is_certified", True)
                    batch["is_certified"] = False
                    self._record_injection(
                        code=code,
                        name=name,
                        table="export_batches",
                        entity_id=batch.get("batch_code", "batch"),
                        field_modified="is_certified",
                        original_value=orig_cert,
                        mutated_value=False,
                        rule=rule,
                    )

    def get_summary(self) -> dict[str, Any]:
        """Convenience method returning the defect report summary."""
        return self.report.get_summary()
