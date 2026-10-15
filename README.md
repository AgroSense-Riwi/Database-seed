#
 AgroSense Café — BD Seed

Módulo de siembra de datos sintéticos para PostgreSQL. Extraído del repo principal [AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework](https://github.com/Pbyte5/AgroSense-Caf-IoT-Monitoring-and-Traceability-Framework).

## Estructura

```
bd_seed/
├── seed/                     # Módulo principal
│   ├── __init__.py
│   ├── __main__.py
│   ├── run_seed.py           # Orquestador CLI
│   ├── faker_generators.py   # Generación sintética con Faker
│   ├── records.py            # Generación de registros de muestra
│   ├── upsert_engine.py      # Motor UPSERT idempotente (CT-06)
│   ├── spatial.py            # Polígonos PostGIS EPSG:4326
│   ├── spatial_geometry.py   # Helpers de geometría WGS84
│   └── spatial_models.py     # Dataclasses y constantes espaciales
├── tests/                    # Tests del módulo
│   ├── test_faker_generators.py
│   ├── test_idempotency_ct06.py
│   ├── test_spatial.py
│   └── test_upsert_engine.py
└── pyproject.toml
```

## Instalación

```bash
pip install faker>=40.43.0
# o con uv:
uv sync --group dev
```

## Uso

```bash
# Modo desarrollo (dataset ligero)
python -m seed --mode dev --seed 42

# Modo producción (volumen completo)
python -m seed --mode prod --seed 42 --defect-rate 0.05

# Con reset (TRUNCATE antes de sembrar)
python -m seed --mode dev --reset
```

## Variables de entorno

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `SEED_PROFILE` | `dev` | Perfil de volumen (`dev` o `prod`) |
| `SEED_RANDOM_STATE` | `42` | Semilla PRNG para reproducibilidad |
| `SEED_DEFECT_GLOBAL_RATE` | `0.05` | Tasa de defectos sintéticos (0.0–1.0) |
| `SEED_RESET_BEFORE_RUN` | `false` | Truncate antes de sembrar |
| `SEED_DB_BATCH_SIZE` | `1000` | Tamaño de lote UPSERT |

## Tests

```bash
pytest
```
