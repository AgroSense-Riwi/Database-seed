"""AgroSense Café - Data Seeding CLI Module."""

from seed.defect_factory import (
    DEFAULT_BASE_DEFECT_RATES,
    DefectFactory,
    DefectReport,
    InjectedDefectRecord,
)
from seed.faker_generators import AgroSenseFakerGenerator
from seed.run_seed import main
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
    "TABLE_UPSERT_REGISTRY",
    "TOPOLOGICAL_TABLE_ORDER",
    "TableUpsertConfig",
    "UpsertEngine",
    "calculate_database_checksum",
    "main",
]
