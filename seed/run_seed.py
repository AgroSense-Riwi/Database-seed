"""AgroSense Café — Reproducible and Idempotent Data Seed Script.

CLI script supporting deterministic seed parameters, modes, defect rates,
and reset operations for PostgreSQL and storage layers.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from faker import Faker

from seed.api_writer import write_api_dataset
from seed.defect_factory import DefectFactory, DefectReport
from seed.faker_generators import AgroSenseFakerGenerator
from seed.records import generate_sample_seed_records, generate_spatial_seed_records
from seed.upsert_engine import (
    UpsertEngine,
    calculate_database_checksum,
    get_database_row_counts,
    get_database_state,
    reset_database_state,
)

logger = logging.getLogger("agrosense.seed")

_LAST_DEFECT_REPORT: DefectReport | None = None


def get_last_defect_report() -> DefectReport | None:
    """Retorna el reporte de la última ejecución de inyección de defectos."""
    return _LAST_DEFECT_REPORT


@dataclass(frozen=True)
class SeedConfig:
    """Configuración inmutable de ejecución para el proceso de seeding.

    Attributes:
        mode: Escala del dataset ('dev' para desarrollo local o 'prod' para volumen completo).
        seed: Semilla entera fija para generadores de números pseudoaleatorios (PRNG).
        defect_rate: Proporción de defectos y anomalías sintéticas a inyectar (0.0 a 1.0).
        reset: Indica si se debe ejecutar un borrado seguro (TRUNCATE CASCADE) previo a la carga.
        batch_size: Tamaño de lote para sentencias multi-row UPSERT (por defecto 1000).
        farms: Número opcional explícito de fincas a generar.
        pilot_farms: Número opcional explícito de fincas con sensores piloto.
        force_roya: Número de fincas con alerta de roya forzada (RN-03, CA-03).
        force_deficit: Número de fincas con alerta de déficit hídrico forzada (RN-04).
        force_deficit_cancel: Número de fincas con alerta cancelada por lluvia (CA-04).
        force_extreme_rain: Número de fincas con lluvia extrema forzada (RN-05).
        emit_bronze: Generar archivos del Data Lake Bronze (F1 a F7).
        bronze_path: Ruta de destino para archivos Bronze.
    """

    mode: str
    seed: int
    defect_rate: float
    reset: bool = False
    batch_size: int = 1000
    farms: int | None = None
    pilot_farms: int | None = None
    force_roya: int = 15
    force_deficit: int = 10
    force_deficit_cancel: int = 5
    force_extreme_rain: int = 8
    emit_bronze: bool = False
    bronze_path: str = "./data/bronze"


def set_reproducible_state(seed: int) -> None:
    """Fija la semilla en los generadores globales para garantizar reproducibilidad determinista.

    Inicializa los generadores pseudoaleatorios del sistema con la semilla especificada,
    cumpliendo con la especificación de reproducibilidad (Deliverable E-03, CT-06).

    Args:
        seed: Número entero para inicializar el estado del PRNG.
    """
    logger.debug("Fijando estado reproducible con semilla=%d", seed)
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    Faker.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def validate_defect_rate(val: str) -> float:
    """Valida y convierte la tasa de defectos ingresada por CLI.

    Garantiza que el valor sea un número decimal acotado en el intervalo [0.0, 1.0].

    Args:
        val: Cadena de texto recibida desde el argumento CLI.

    Returns:
        float: Valor decimal validado entre 0.0 y 1.0.

    Raises:
        argparse.ArgumentTypeError: Si el valor no es numérico o está fuera de rango.
    """
    try:
        fval = float(val)
    except ValueError as err:
        msg = f"La tasa de defectos debe ser un float, recibido: {val!r}"
        raise argparse.ArgumentTypeError(msg) from err

    if not 0.0 <= fval <= 1.0:
        raise argparse.ArgumentTypeError(
            f"La tasa de defectos debe estar entre 0.0 y 1.0, recibido: {fval}"
        )
    return fval


def build_parser() -> argparse.ArgumentParser:
    """Construye y configura el parser de argumentos de línea de comandos (CLI).

    Configura los parámetros admitidos y lee las variables de entorno como valores
    por defecto en caso de no ser provistos explícitamente en la terminal.

    Returns:
        argparse.ArgumentParser: Objeto parser listo para procesar argumentos.
    """
    # 1. Obtener valores por defecto desde variables de entorno (con fallbacks seguros)
    env_mode = os.getenv("SEED_PROFILE", "dev").lower()
    if env_mode == "full":
        env_mode = "prod"
    default_mode = env_mode if env_mode in {"dev", "prod"} else "dev"

    try:
        default_seed = int(os.getenv("SEED_RANDOM_STATE", "42"))
    except ValueError:
        default_seed = 42

    try:
        default_defect_rate = float(os.getenv("SEED_DEFECT_GLOBAL_RATE", "0.05"))
        if not 0.0 <= default_defect_rate <= 1.0:
            default_defect_rate = 0.05
    except ValueError:
        default_defect_rate = 0.05

    try:
        default_batch_size = int(os.getenv("SEED_DB_BATCH_SIZE", "1000"))
        if default_batch_size <= 0:
            default_batch_size = 1000
    except ValueError:
        default_batch_size = 1000

    env_reset = os.getenv("SEED_RESET_BEFORE_RUN", "false").lower() in {"true", "1", "yes"}

    try:
        default_force_roya = int(os.getenv("SEED_FORCE_ROYA_FARMS", "15"))
    except ValueError:
        default_force_roya = 15

    try:
        default_force_deficit = int(os.getenv("SEED_FORCE_DEFICIT_FARMS", "10"))
    except ValueError:
        default_force_deficit = 10

    try:
        default_force_deficit_cancel = int(os.getenv("SEED_FORCE_DEFICIT_CANCEL", "5"))
    except ValueError:
        default_force_deficit_cancel = 5

    try:
        default_force_extreme_rain = int(os.getenv("SEED_FORCE_EXTREME_RAIN_FARMS", "8"))
    except ValueError:
        default_force_extreme_rain = 8

    env_emit_bronze = os.getenv("SEED_OUTPUT_BRONZE_FILES", "false").lower() in {
        "true",
        "1",
        "yes",
    }
    default_bronze_path = os.getenv("BRONZE_LANDING_PATH", "./data/bronze")

    # 2. Definición del parser con descripción del entregable
    parser = argparse.ArgumentParser(
        prog="run_seed.py",
        description=(
            "AgroSense Café - Ejecutor reproducible e idempotente de datos sintéticos. "
            "Puebla la base de datos PostgreSQL y las capas de almacenamiento (Data Lake Bronze)."
        ),
    )

    # Argumento: --mode
    parser.add_argument(
        "--mode",
        choices=["dev", "prod", "full"],
        default=default_mode,
        help=(
            f"Perfil de volumen: 'dev' (130 fincas para desarrollo local) "
            f"o 'prod' (1,300 fincas para volumen completo). Por defecto: {default_mode}."
        ),
    )

    # Argumento: --seed
    parser.add_argument(
        "--seed",
        type=int,
        default=default_seed,
        help=(
            f"Semilla entera para el PRNG para asegurar determinismo. Por defecto: {default_seed}."
        ),
    )

    # Argumento: --defect-rate
    parser.add_argument(
        "--defect-rate",
        type=validate_defect_rate,
        default=default_defect_rate,
        dest="defect_rate",
        help=(
            f"Proporción de defectos de calidad a inyectar (0.0 a 1.0). "
            f"Por defecto: {default_defect_rate}."
        ),
    )

    # Argumento: --reset
    parser.add_argument(
        "--reset",
        action="store_true",
        default=env_reset,
        help="Limpia las tablas y reinicia secuencias antes de sembrar (TRUNCATE CASCADE).",
    )

    # Argumento: --batch-size
    parser.add_argument(
        "--batch-size",
        type=int,
        default=default_batch_size,
        dest="batch_size",
        help=f"Tamaño de lote para sentencias multi-row UPSERT. Por defecto: {default_batch_size}.",
    )

    # Argumentos para volumen configurable
    parser.add_argument(
        "--farms",
        type=int,
        default=None,
        dest="farms",
        help="Número total de fincas a generar (sobrescribe el valor predeterminado del perfil).",
    )
    parser.add_argument(
        "--pilot-farms",
        type=int,
        default=None,
        dest="pilot_farms",
        help="Número de fincas piloto con sensores IoT instalados.",
    )

    # Argumentos para escenarios agronómicos forzados
    parser.add_argument(
        "--force-roya",
        type=int,
        default=default_force_roya,
        dest="force_roya",
        help="Fincas con alerta de roya forzada (RN-03, CA-03). Por defecto: 15.",
    )
    parser.add_argument(
        "--force-deficit",
        type=int,
        default=default_force_deficit,
        dest="force_deficit",
        help="Fincas con alerta de déficit hídrico forzada (RN-04). Por defecto: 10.",
    )
    parser.add_argument(
        "--force-rain-save",
        type=int,
        default=default_force_deficit_cancel,
        dest="force_deficit_cancel",
        help="Fincas con déficit cancelado por pronóstico de lluvia (CA-04). Por defecto: 5.",
    )
    parser.add_argument(
        "--force-rain",
        type=int,
        default=default_force_extreme_rain,
        dest="force_extreme_rain",
        help="Fincas con precipitación extrema forzada > 120mm/72h (RN-05). Por defecto: 8.",
    )

    # Argumentos para Data Lake Bronze
    parser.add_argument(
        "--emit-bronze",
        action="store_true",
        default=env_emit_bronze,
        dest="emit_bronze",
        help="Exporta las 7 fuentes secundarias (F1 a F7) a la capa Bronze del Data Lake.",
    )
    parser.add_argument(
        "--bronze-path",
        type=str,
        default=default_bronze_path,
        dest="bronze_path",
        help=f"Ruta de destino para la capa Bronze. Por defecto: {default_bronze_path}.",
    )

    return parser


def parse_args(args: Sequence[str] | None = None) -> SeedConfig:
    """Parsea y valida los argumentos CLI, retornando una configuración inmutable.

    Args:
        args: Lista opcional de argumentos a parsear (None para usar sys.argv).

    Returns:
        SeedConfig: Objeto de configuración validado.
    """
    parser = build_parser()
    parsed = parser.parse_args(args)
    normalized_mode = "prod" if parsed.mode == "full" else parsed.mode
    return SeedConfig(
        mode=normalized_mode,
        seed=parsed.seed,
        defect_rate=parsed.defect_rate,
        reset=parsed.reset,
        batch_size=parsed.batch_size,
        farms=parsed.farms,
        pilot_farms=parsed.pilot_farms,
        force_roya=parsed.force_roya,
        force_deficit=parsed.force_deficit,
        force_deficit_cancel=parsed.force_deficit_cancel,
        force_extreme_rain=parsed.force_extreme_rain,
        emit_bronze=parsed.emit_bronze,
        bronze_path=parsed.bronze_path,
    )


def emit_bronze_layers(
    dataset: dict[str, list[dict[str, Any]]],
    base_path: str = "./data/bronze",
) -> None:
    """Exporta las 7 fuentes secundarias (F1 a F7) a la capa Bronze del Data Lake.

    Simula el almacenamiento de datos brutos inmutables en formato JSON para S3 o local.
    """
    import json

    os.makedirs(base_path, exist_ok=True)
    logger.info("Exportando capas del Data Lake (Bronze) en: %s", base_path)

    # F1: Requerimientos nutricionales Kaggle
    f1_dir = os.path.join(base_path, "crop_nutrient_references")
    os.makedirs(f1_dir, exist_ok=True)
    with open(os.path.join(f1_dir, "references.json"), "w", encoding="utf-8") as f:
        json.dump(dataset.get("crop_nutrient_references", []), f, indent=2, default=str)

    # F2: NASA POWER Satelital Diario
    f2_dir = os.path.join(base_path, "nasa_power_daily")
    os.makedirs(f2_dir, exist_ok=True)
    farms = dataset.get("farms", [])
    nasa_records = [
        {
            "farm_id": farm.get("farm_id"),
            "latitude": farm.get("latitude"),
            "longitude": farm.get("longitude"),
            "observation_date": "2026-10-18",
            "t2m_mean_celsius": 22.4,
            "rh2m_pct": 82.5,
            "prectotcorr_mm": 12.0,
            "ingested_at": "2026-10-18T05:00:00Z",
        }
        for farm in farms[: min(30, len(farms))]
    ]
    with open(os.path.join(f2_dir, "nasa_power_daily.json"), "w", encoding="utf-8") as f:
        json.dump(nasa_records, f, indent=2, default=str)

    # F3: Open-Meteo Pronóstico 7 días
    f3_dir = os.path.join(base_path, "open_meteo_forecast")
    os.makedirs(f3_dir, exist_ok=True)
    forecast_records = [
        {
            "farm_id": farm.get("farm_id"),
            "forecast_run_ts": "2026-10-18T00:00:00Z",
            "target_hour_ts": "2026-10-18T12:00:00Z",
            "temp_2m_celsius": 23.5,
            "relative_humidity_pct": 86.0,
            "precipitation_mm": 4.5,
        }
        for farm in farms[: min(30, len(farms))]
    ]
    with open(os.path.join(f3_dir, "forecast.json"), "w", encoding="utf-8") as f:
        json.dump(forecast_records, f, indent=2, default=str)

    # F4: IoT Telemetry Streams
    f4_dir = os.path.join(base_path, "iot_telemetry")
    os.makedirs(f4_dir, exist_ok=True)
    telemetry_records = [
        {
            "sensor_id": sensor.get("sensor_id"),
            "farm_id": sensor.get("farm_id"),
            "sensor_type": sensor.get("sensor_type"),
            "raw_value": 24.5,
            "battery_pct": sensor.get("battery_level", 95.0),
            "status": sensor.get("status", "ACTIVE"),
        }
        for sensor in dataset.get("iot_sensors", [])
    ]
    with open(os.path.join(f4_dir, "telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(telemetry_records, f, indent=2, default=str)

    # F5: Entregas de Cosecha
    f5_dir = os.path.join(base_path, "harvest_deliveries")
    os.makedirs(f5_dir, exist_ok=True)
    with open(os.path.join(f5_dir, "deliveries.json"), "w", encoding="utf-8") as f:
        json.dump(dataset.get("harvest_deliveries", []), f, indent=2, default=str)

    # F6: Reportes de Laboratorio de Suelos
    f6_dir = os.path.join(base_path, "soil_lab_reports")
    os.makedirs(f6_dir, exist_ok=True)
    with open(os.path.join(f6_dir, "soil_analyses.json"), "w", encoding="utf-8") as f:
        json.dump(dataset.get("soil_lab_analyses", []), f, indent=2, default=str)

    # F7: Compradores y Contratos
    f7_dir = os.path.join(base_path, "international_buyers")
    os.makedirs(f7_dir, exist_ok=True)
    with open(os.path.join(f7_dir, "contracts.json"), "w", encoding="utf-8") as f:
        json.dump(dataset.get("buyer_batch_contracts", []), f, indent=2, default=str)

    logger.info("Capas Bronze (F1 a F7) exportadas exitosamente en: %s", base_path)


def run_seed(
    config: SeedConfig | None = None,
    *,
    seed_value: int | None = None,
    mode: str = "dev",
    defect_rate: float = 0.05,
    reset: bool = False,
    batch_size: int = 1000,
    farms: int | None = None,
    pilot_farms: int | None = None,
    emit_bronze: bool = False,
    bronze_path: str = "./data/bronze",
    **kwargs: Any,
) -> int:
    """Orquesta y ejecuta el proceso de generación y siembra de datos con Faker y UPSERT.

    Admite tanto un objeto inmutable SeedConfig como parámetros por palabra clave
    para máxima compatibilidad con tests.

    Args:
        config: Parámetros validados para la ejecución del seed (opcional).
        seed_value: Semilla PRNG opcional si no se provee config.
        mode: Perfil de escala ('dev' o 'prod') si no se provee config.
        defect_rate: Proporción de defectos si no se provee config.
        reset: Limpieza previa si no se provee config.
        batch_size: Tamaño de lote si no se provee config.
        farms: Número explícito de fincas.
        pilot_farms: Número explícito de fincas con sensores piloto.
        emit_bronze: Generar archivos Bronze Data Lake.
        bronze_path: Ruta de destino Bronze.

    Returns:
        int: Código de salida (0 para éxito, distinto de 0 en caso de error).
    """
    if config is None:
        seed = seed_value if seed_value is not None else 42
        config = SeedConfig(
            mode=mode,
            seed=seed,
            defect_rate=defect_rate,
            reset=reset,
            batch_size=batch_size,
            farms=farms,
            pilot_farms=pilot_farms,
            emit_bronze=emit_bronze,
            bronze_path=bronze_path,
        )

    try:
        logger.info("Iniciando proceso de seeding de AgroSense Café...")
        logger.info(
            "Configuración activa: mode=%s, seed=%d, defect_rate=%.2f, reset=%s, batch_size=%d",
            config.mode,
            config.seed,
            config.defect_rate,
            config.reset,
            config.batch_size,
        )

        # 1. Asegurar estado pseudoaleatorio determinista con la semilla configurada
        set_reproducible_state(config.seed)

        # 2. Generación determinista de entidades sintéticas con integración de Faker
        faker_gen = AgroSenseFakerGenerator(seed=config.seed)
        dataset = faker_gen.generate_all(
            mode=config.mode,
            farms_count=config.farms,
            pilot_count=config.pilot_farms,
        )
        clean_dataset = dataset
        farms_count = len(dataset.get("farms", []))
        logger.info(
            "Dataset sintético generado con Faker: %d fincas, %d productores, %d sensores.",
            farms_count,
            len(dataset.get("producers", [])),
            len(dataset.get("iot_sensors", [])),
        )

        # 3. Inyección configurable de defectos de calidad de datos (AGRO-05C)
        global _LAST_DEFECT_REPORT
        defect_factory = DefectFactory(defect_rate=config.defect_rate, seed=config.seed)
        dataset = defect_factory.apply(dataset)
        _LAST_DEFECT_REPORT = defect_factory.report
        summary = defect_factory.get_summary()
        logger.info(
            "DefectFactory (AGRO-05C): %d defectos inyectados (rate=%.2f). Resumen: %s",
            summary["total_defects_injected"],
            summary["global_defect_rate"],
            summary["defects_by_code"],
        )

        # 4. Motor de Idempotencia UPSERT y preparación de sentencias SQL
        engine = UpsertEngine(batch_size=config.batch_size)

        if config.reset:
            truncate_stmt = engine.build_truncate_sql()
            logger.info("Modo --reset activo: Limpieza atómica preparada:\n  %s", truncate_stmt)
            reset_database_state()

        # Aplicar datos en el almacén de base de datos simulado (emula ejecución SQL)
        engine.apply_dataset_upsert(dataset)

        sql_statements = engine.build_all_upsert_statements(dataset)
        total_stmts = sum(len(stmts) for stmts in sql_statements.values())
        logger.info(
            "Sentencias UPSERT (ON CONFLICT) en 5 niveles topológicos: %d en %d tablas.",
            total_stmts,
            len(sql_statements),
        )

        # 4. Certificación estricta de idempotencia y verificación de no-inflación de filas (CT-06)
        idempotency_report = engine.verify_idempotency(dataset)
        if not idempotency_report["is_idempotent"] or idempotency_report["row_inflation_detected"]:
            logger.error("Fallo crítico: Violación de idempotencia detectada en la verificación.")
            return 1

        logger.info(
            "Certificación CT-06 aprobada: 0 inflación de filas y 0 duplicados en %d tablas.",
            idempotency_report["tables_tested"],
        )

        database_url = os.getenv("DATABASE_URL")
        if database_url:
            write_api_dataset(clean_dataset, database_url, reset=config.reset)
            logger.info("Dataset compatible con la API escrito en PostgreSQL.")
        else:
            logger.info("DATABASE_URL no está configurada; se omite la escritura en PostgreSQL.")

        # 5. Geometrías espaciales de muestra para diagnóstico CLI
        sample_data, reserve_data = generate_spatial_seed_records(
            generate_sample_seed_records(count=min(5, farms_count)), seed=config.seed
        )
        logger.info(
            "Geometrías generadas: %d fincas y %d reservas forestales (SRID=%d).",
            len(sample_data),
            len(reserve_data),
            4326,
        )

        # 6. Exportar capas Bronze si está solicitado
        if config.emit_bronze:
            emit_bronze_layers(dataset, base_path=config.bronze_path)

        logger.info("Proceso de seeding finalizado con éxito.")
        return 0
    except Exception as err:
        logger.error("Error crítico durante la ejecución del seed: %s", err, exc_info=True)
        return 1


def main(argv: Sequence[str] | None = None) -> None:
    """Punto de entrada principal para el ejecutor CLI.

    Configura el sistema de logging estándar de la aplicación y despacha la ejecución.

    Args:
        argv: Lista opcional de argumentos para el parser.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    )
    config = parse_args(argv)
    exit_code = run_seed(config)
    if exit_code != 0:
        raise SystemExit(exit_code)


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
