# AgroSense Café — DB Seed

Synthetic data seeding module for PostgreSQL/PostGIS. Extracted from the main repository [AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework](https://github.com/Pbyte5/AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework).

## Project Structure

```
Database-seed/
├── seed/                       # Main module (run with `python -m seed`)
│   ├── __main__.py             # Entry point
│   ├── run_seed.py             # CLI orchestrator
│   ├── api_writer.py           # Real PostgreSQL writer (INSERT ... ON CONFLICT on business keys)
│   ├── defect_factory.py       # Configurable defect injection engine (AGRO-05C)
│   ├── faker_generators.py     # Synthetic generation with Faker
│   ├── records.py              # Sample records generation
│   ├── reproducibility.py      # Global PRNG seeding
│   ├── upsert_engine.py        # In-memory UPSERT simulation (unit-level only, no SQL)
│   ├── spatial.py              # PostGIS EPSG:4326 polygons & spatial overlap
│   ├── spatial_geometry.py     # WGS84 geometry helpers (intersection, area in ha)
│   ├── spatial_models.py       # Dataclasses and spatial constants
│   └── telemetry_generators.py # IoT telemetry anomaly generators (DEF-01, DEF-02)
├── tests/                      # Test suite (conftest.py isolates tests from real DBs)
├── Dockerfile                  # Seed image (standalone build context: this repo)
├── docker-compose.yml          # PostGIS + one-shot seed job (profile `seed`)
└── pyproject.toml
```

## Installation

```bash
uv sync            # runtime + dev dependencies (pyproject.toml / uv.lock)
```

## Usage

The only supported entry point is the `seed` module:

```bash
# Development mode (lightweight dataset) — generation only, no DB write
uv run python -m seed --mode dev --seed 42

# Write to PostgreSQL: set DATABASE_URL (postgresql:// or postgresql+psycopg://)
DATABASE_URL=postgresql://agrosense:***@localhost:5432/agrosense_db uv run python -m seed

# Production volume
uv run python -m seed --mode prod --seed 42 --defect-rate 0.05

# Reset (TRUNCATE ... CASCADE) before seeding — see "Reset safety" below
uv run python -m seed --mode dev --reset
```

### Database schema (prerequisite)

The schema is owned by the **API repository** (Alembic revisions under
`apps/api/migrations`). This seed never creates tables: it expects the database to
be migrated already and aborts with `SchemaNotReadyError` if any API table is
missing. From the API repository:

```bash
cd apps/api
DATABASE_URL=postgresql+psycopg://agrosense:***@<db-host>:5432/agrosense_db uv run alembic upgrade head
```

### Idempotency (CT-06)

`seed/api_writer.py` writes every table with `INSERT ... ON CONFLICT` executed by
PostgreSQL. Conflict targets follow `seed_data_reproducibility_strategy.md` §3 when
the API schema has a matching UNIQUE constraint (`farms.farm_code`,
`producers.document_number`, `international_buyers.client_id`,
`export_batches.batch_code`, `coffee_varieties.variety_name`); otherwise the
deterministic UUIDv5/catalogue primary key is used (`users` has no `email` column
and `municipalities` has no `dane_code` column in the API schema yet).

The real CT-06 check is `tests/test_integration_postgres.py`: it seeds twice and
compares per-table row counts and MD5 checksums computed in SQL. It is skipped
unless `TEST_DATABASE_URL` points to a migrated, disposable `*_test_db` database:

```bash
TEST_DATABASE_URL=postgresql://agrosense:***@localhost:5432/agrosense_test_db uv run pytest -m integration
```

### Reset safety

`--reset` / `SEED_RESET_BEFORE_RUN=true` truncates the API tables. It is refused
unless the connected database name ends with `_test_db` (e.g. `agrosense_test_db`)
or `SEED_RESET_CONFIRM_DB` equals the exact name of the connected database.

## Despliegue separado de la base de datos

`docker-compose.yml` levanta PostgreSQL/PostGIS (`db`) y define el job de siembra
`seed` bajo el perfil `seed`. El contenedor `seed` **no** aplica migraciones: el
esquema pertenece al repositorio API. La API no se inicia en este servidor.

Desde la raíz de este repositorio, copia `.env.example` como `.env` y reemplaza los
valores de ejemplo. `POSTGRES_BIND_ADDRESS` debe ser la IP privada asignada a la
interfaz de red de este servidor DB.

1. Levanta la base de datos:

   ```bash
   docker compose --env-file .env up -d db
   ```

2. Aplica las migraciones desde el repositorio API apuntando a esta BD
   (`alembic upgrade head`, ver sección *Database schema*).

3. Ejecuta la siembra (job de una sola vez):

   ```bash
   docker compose --env-file .env --profile seed run --rm --build seed
   ```

   El comando debe terminar con código `0`; luego puedes iniciar la API en su
   servidor configurando su URL de PostgreSQL con la IP privada de DB.

En el servidor API, configura `AGROSENSE_DATABASE_URL` con el esquema
`postgresql+asyncpg://` y `DATABASE_URL` con `postgresql+psycopg://`; ambas deben
usar las mismas credenciales, la IP privada de DB y el nombre de la base de datos.

El puerto publicado por defecto es `5432`. Permite ese puerto en el firewall solo
desde la IP del servidor API y establece en la API la URL de PostgreSQL usando la
IP privada del servidor DB. Puedes cambiar el puerto con `POSTGRES_PORT`. Usa una
contraseña URL-safe en `POSTGRES_PASSWORD` para la URL de conexión.

La semilla es idempotente y puede re-ejecutarse. Solo carga las entidades
disponibles en el esquema actual de la API; los catálogos IoT, de suelos y
espaciales exclusivos del generador no se insertan porque la API aún no tiene
tablas equivalentes.

## Environment Variables

| Variable | Default Value | Description |
|---|---|---|
| `DATABASE_URL` | _(unset)_ | Target PostgreSQL; when unset nothing is written |
| `SEED_PROFILE` | `dev` | Volume profile (`dev` or `prod`) |
| `SEED_RANDOM_STATE` | `42` | PRNG seed for reproducibility |
| `SEED_DEFECT_GLOBAL_RATE` | `0.05` | Synthetic defect rate (0.0–1.0) |
| `SEED_RESET_BEFORE_RUN` | `false` | Truncate tables before seeding (guarded) |
| `SEED_RESET_CONFIRM_DB` | _(empty)_ | Must equal the DB name to allow a reset on a non `*_test_db` DB |
| `SEED_DB_BATCH_SIZE` | `1000` | Batch size setting |
| `TEST_DATABASE_URL` | _(unset)_ | Opt-in for integration tests (`*_test_db` only) |

## Tests

```bash
uv run pytest          # unit tests; never touch a real DB (DATABASE_URL/PG* scrubbed)
```
