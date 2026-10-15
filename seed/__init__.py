"""AgroSense Café - Data Seeding CLI Module."""

from seed.defect_factory import (
    DEFAULT_BASE_DEFECT_RATES,
    DefectFactory,
    DefectReport,
    InjectedDefectRecord,
)
from seed.faker_generators import AgroSenseFakerGenerator
from seed.run_seed import main
from seed.spatial import PostGISSpatialGenerator, SpatialOverlapGenerator
from seed.spatial_models import SpatialOverlapResult, SpatialPolygonResult
from seed.telemetry_generators import (
    calculate_series_stddev,
    count_out_of_order_inversions,
    generate_sensor_telemetry_series,
    generate_telemetry_dataset,
    inject_flatlining_anomaly,
    inject_out_of_order_anomaly,
)
from seed.upsert_engine import (
    TABLE_UPSERT_REGISTRY,
    TOPOLOGICAL_TABLE_ORDER,
    ConflictStrategy,
    TableUpsertConfig,
    UpsertEngine,
    calculate_database_checksum,
)

__all__ = [
    "DEFAULT_BASE_DEFECT_RATES",
    "AgroSenseFakerGenerator",
    "ConflictStrategy",
    "DefectFactory",
    "DefectReport",
    "InjectedDefectRecord",
    "PostGISSpatialGenerator",
    "SpatialOverlapGenerator",
    "SpatialOverlapResult",
    "SpatialPolygonResult",
    "TABLE_UPSERT_REGISTRY",
    "TOPOLOGICAL_TABLE_ORDER",
    "TableUpsertConfig",
    "UpsertEngine",
    "calculate_database_checksum",
    "calculate_series_stddev",
    "count_out_of_order_inversions",
    "generate_sensor_telemetry_series",
    "generate_telemetry_dataset",
    "inject_flatlining_anomaly",
    "inject_out_of_order_anomaly",
    "main",
]
