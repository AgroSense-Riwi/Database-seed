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
│   ├── spatial.py            # PostGIS EPSG:4326 polygons & spatial overlap
│   ├── spatial_geometry.py   # WGS84 geometry helpers
│   ├── spatial_models.py     # Dataclasses and spatial constants
│   └── telemetry_generators.py # IoT telemetry anomaly generators (DEF-01, DEF-02)
├── tests/                    # Module test suite
│   ├── test_defect_factory.py
│   ├── test_defect_frequency_suite.py
│   ├── test_faker_generators.py
│   ├── test_idempotency_ct06.py
│   ├── test_run_seed.py
│   ├── test_spatial.py
│   ├── test_spatial_overlap.py
│   ├── test_telemetry_generators.py
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

## Despliegue separado de la base de datos

`docker-compose.yml` levanta únicamente PostgreSQL/PostGIS y el contenedor de
siembra. Cuando PostgreSQL está saludable, el contenedor aplica las migraciones
Alembic de la API y luego inserta datos compatibles con sus tablas. La API no se
inicia en este servidor.

Desde la raíz del repositorio, copia `database/.env.example` como
`database/.env` y reemplaza los valores de ejemplo. `POSTGRES_BIND_ADDRESS` debe
ser la IP privada asignada a la interfaz de red de este servidor DB. Después ejecuta:

```bash
docker compose --env-file database/.env -f database/docker-compose.yml up -d --build
```

Espera a que finalice la carga antes de arrancar la API:

```bash
docker compose --env-file database/.env -f database/docker-compose.yml logs -f seed
```

El contenedor `seed` debe terminar con código `0`; luego puedes iniciar la API en su
servidor configurando su URL de PostgreSQL con la IP privada de DB.

En el servidor API, configura `AGROSENSE_DATABASE_URL` con el esquema
`postgresql+asyncpg://` y `DATABASE_URL` con `postgresql+psycopg://`; ambas deben
usar las mismas credenciales, la IP privada de DB y el nombre de la base de datos.

El puerto publicado por defecto es `5432`. Permite ese puerto en el firewall solo
desde la IP del servidor API y establece en la API la URL de PostgreSQL usando la
IP privada del servidor DB. Puedes cambiar el puerto con `POSTGRES_PORT`. Usa una
contraseña URL-safe en `POSTGRES_PASSWORD` para la URL de conexión.

La semilla es idempotente y vuelve a ejecutarse al iniciar el servicio `seed`. Solo
carga las entidades disponibles en el esquema actual de la API; los catálogos IoT,
de suelos y espaciales exclusivos del generador no se insertan porque la API aún no
tiene tablas equivalentes.

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
