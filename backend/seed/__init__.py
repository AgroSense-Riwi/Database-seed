"""AgroSense Café — Backend seed module."""

from __future__ import annotations

from seed.defect_factory import DefectFactory, DefectReport
from seed.faker_generators import AgroSenseFakerGenerator
from seed.records import (
    generate_faker_seed_dataset,
    generate_sample_seed_records,
    generate_spatial_seed_records,
)
from seed.run_seed import (
    SeedConfig,
    build_parser,
    calculate_database_checksum,
    emit_bronze_layers,
    get_database_row_counts,
    get_database_state,
    main,
    parse_args,
    reset_database_state,
    run_seed,
    set_reproducible_state,
    validate_defect_rate,
)
from seed.spatial import PostGISSpatialGenerator
from seed.upsert_engine import (
    TABLE_UPSERT_REGISTRY,
    TOPOLOGICAL_TABLE_ORDER,
    ConflictStrategy,
    TableUpsertConfig,
    UpsertEngine,
)

__all__ = [
    "ConflictStrategy",
    "DefectFactory",
    "DefectReport",
    "AgroSenseFakerGenerator",
    "PostGISSpatialGenerator",
    "SeedConfig",
    "TABLE_UPSERT_REGISTRY",
    "TOPOLOGICAL_TABLE_ORDER",
    "TableUpsertConfig",
    "UpsertEngine",
    "build_parser",
    "calculate_database_checksum",
    "emit_bronze_layers",
    "generate_faker_seed_dataset",
    "generate_sample_seed_records",
    "generate_spatial_seed_records",
    "get_database_row_counts",
    "get_database_state",
    "main",
    "parse_args",
    "reset_database_state",
    "run_seed",
    "set_reproducible_state",
    "validate_defect_rate",
]
