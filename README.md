# AgroSense Café — DB Seed

Synthetic data seeding module for PostgreSQL. Extracted from the main repository [AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework](https://github.com/Pbyte5/AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework).

## Project Structure

```
Database-seed/
├── seed/                     # Main module
│   ├── __init__.py
│   ├── __main__.py
│   ├── run_seed.py           # CLI orchestrator
│   ├── defect_factory.py     # Configurable defect injection engine (AGRO-05C)
│   ├── faker_generators.py   # Synthetic generation with Faker
│   ├── records.py            # Sample records generation
│   ├── upsert_engine.py      # Idempotent UPSERT engine (CT-06)
│   ├── spatial.py            # PostGIS EPSG:4326 polygons
│   ├── spatial_geometry.py   # WGS84 geometry helpers
│   └── spatial_models.py     # Dataclasses and spatial constants
├── tests/                    # Module test suite
│   ├── test_defect_factory.py
│   ├── test_faker_generators.py
│   ├── test_idempotency_ct06.py
│   ├── test_run_seed.py
│   ├── test_spatial.py
│   └── test_upsert_engine.py
└── pyproject.toml
```

## Installation

```bash
pip install faker>=40.43.0
# or with uv:
uv sync --group dev
```

## Usage

```bash
# Development mode (lightweight dataset)
python -m seed --mode dev --seed 42

# Production mode (full volume)
python -m seed --mode prod --seed 42 --defect-rate 0.05

# With reset (TRUNCATE before seeding)
python -m seed --mode dev --reset
```

## Environment Variables

| Variable | Default Value | Description |
|---|---|---|
| `SEED_PROFILE` | `dev` | Volume profile (`dev` or `prod`) |
| `SEED_RANDOM_STATE` | `42` | PRNG seed for reproducibility |
| `SEED_DEFECT_GLOBAL_RATE` | `0.05` | Synthetic defect rate (0.0–1.0) |
| `SEED_RESET_BEFORE_RUN` | `false` | Truncate tables before seeding |
| `SEED_DB_BATCH_SIZE` | `1000` | Multi-row UPSERT batch size |

## Tests

```bash
pytest
```
