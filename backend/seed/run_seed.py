"""AgroSense Café — Reproducible and Idempotent Data Seed Script.

Backend CLI entrypoint for running the seed simulation.
"""

from __future__ import annotations

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

if __name__ == "__main__":
    main()

__all__ = [
    "SeedConfig",
    "build_parser",
    "calculate_database_checksum",
    "emit_bronze_layers",
    "get_database_row_counts",
    "get_database_state",
    "main",
    "parse_args",
    "reset_database_state",
    "run_seed",
    "set_reproducible_state",
    "validate_defect_rate",
]
