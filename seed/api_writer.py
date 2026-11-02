"""Projection and PostgreSQL writer for the API's operational schema.

The schema itself is owned by the API repository (Alembic revisions
``927ccb53d091`` + ``c1a8f93e2b45``). This module never creates tables: it
expects ``alembic upgrade head`` to have been run against the target database
and fails fast with :class:`SchemaNotReadyError` otherwise.

Idempotency (CT-06) is enforced by PostgreSQL itself through
``INSERT ... ON CONFLICT (<business key>)``. The conflict target of each table
follows ``seed_data_reproducibility_strategy.md`` §3 whenever the API schema
declares a matching UNIQUE constraint/index; otherwise the (deterministic
UUIDv5 / fixed catalogue) primary key is used. See ``CONFLICT_TARGETS``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Any

API_TABLES: dict[str, tuple[str, ...]] = {
    "coffee_varieties": ("variety_id", "variety_name"),
    "users": ("user_id", "full_name", "role"),
    "producers": (
        "producer_id",
        "document_number",
        "full_name",
        "phone_number",
        "cooperative_join_date",
    ),
    "international_buyers": ("buyer_id", "client_id", "buyer_name"),
    "municipalities": ("municipality_id", "name"),
    "farms": (
        "farm_id",
        "farm_code",
        "producer_id",
        "municipality_id",
        "latitude",
        "longitude",
        "cultivated_area_ha",
        "water_usage_m3_ton",
        "overlaps_reserve",
    ),
    "farm_plots": ("plot_id", "farm_id", "variety_id", "plot_name", "crop_age_years"),
    "harvest_deliveries": (
        "delivery_id",
        "farm_id",
        "plot_id",
        "delivery_date",
        "delivered_weight_kg",
    ),
    "export_batches": (
        "batch_id",
        "batch_code",
        "total_weight_kg",
        "traced_weight_kg",
        "is_exportable",
        "is_certified",
        "weighted_water_m3_ton",
    ),
    "batch_farm_compositions": (
        "composition_id",
        "batch_id",
        "delivery_id",
        "farm_id",
        "contributed_kg",
        "share_percentage",
    ),
    "buyer_batch_contracts": ("contract_id", "batch_id", "buyer_id"),
    "cupping_evaluations": (
        "cupping_id",
        "batch_id",
        "quality_chief_id",
        "sca_total_score",
        "acidity_score",
        "body_score",
        "sensory_notes",
    ),
    "farm_reserve_overlaps": (
        "overlap_id",
        "farm_id",
        "reserve_name",
        "overlap_geometry",
    ),
}

PRIMARY_KEYS: dict[str, str] = {
    "coffee_varieties": "variety_id",
    "users": "user_id",
    "producers": "producer_id",
    "international_buyers": "buyer_id",
    "municipalities": "municipality_id",
    "farms": "farm_id",
    "farm_plots": "plot_id",
    "harvest_deliveries": "delivery_id",
    "export_batches": "batch_id",
    "batch_farm_compositions": "composition_id",
    "buyer_batch_contracts": "contract_id",
    "cupping_evaluations": "cupping_id",
    "farm_reserve_overlaps": "overlap_id",
}

# ON CONFLICT target per table. Business keys come from
# seed_data_reproducibility_strategy.md §3 and are only used when the API
# migration 927ccb53d091 declares a UNIQUE constraint/index on them:
#   coffee_varieties.variety_name  -> uq_coffee_varieties_variety_name
#   producers.document_number      -> uq_producers_document_number
#   international_buyers.client_id -> ix_international_buyers_client_id (unique)
#   farms.farm_code                -> ix_farms_farm_code (unique)
#   export_batches.batch_code      -> ix_export_batches_batch_code (unique)
# Documented keys WITHOUT a backing column/constraint in the API schema
# (fallback to the deterministic primary key):
#   users(email)              -> API ``users`` has no ``email`` column.
#   municipalities(dane_code) -> API ``municipalities`` has no ``dane_code`` column.
CONFLICT_TARGETS: dict[str, tuple[str, ...]] = {
    "coffee_varieties": ("variety_name",),
    "users": ("user_id",),
    "producers": ("document_number",),
    "international_buyers": ("client_id",),
    "municipalities": ("municipality_id",),
    "farms": ("farm_code",),
    "farm_plots": ("plot_id",),
    "harvest_deliveries": ("delivery_id",),
    "export_batches": ("batch_code",),
    "batch_farm_compositions": ("composition_id",),
    "buyer_batch_contracts": ("contract_id",),
    "cupping_evaluations": ("cupping_id",),
    "farm_reserve_overlaps": ("overlap_id",),
}

# Tables documented as immutable / static catalogues -> DO NOTHING (docs §3).
DO_NOTHING_TABLES: frozenset[str] = frozenset({"municipalities", "batch_farm_compositions"})

# Columns that need an explicit SQL conversion of their bound parameter.
_PLACEHOLDER_WRAPPERS: dict[tuple[str, str], str] = {
    ("farm_reserve_overlaps", "overlap_geometry"): "ST_GeomFromEWKT",
}

# Databases that may be truncated without explicit confirmation
# (postgres-docker.md provisions ``agrosense_test_db`` for pytest).
TEST_DATABASE_SUFFIXES: tuple[str, ...] = ("_test_db", "_test")
RESET_CONFIRM_ENV = "SEED_RESET_CONFIRM_DB"


class ResetNotAllowedError(RuntimeError):
    """Raised when a destructive TRUNCATE is requested on a non-test database."""


class SchemaNotReadyError(RuntimeError):
    """Raised when the API schema (Alembic migrations) is missing in the target DB."""


def build_api_dataset(
    dataset: Mapping[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Map generated records to columns supported by the API's Alembic schema."""
    mappings: dict[str, tuple[str, Any]] = {
        "coffee_varieties": (
            "coffee_varieties",
            lambda row: {**row, "variety_name": row["name"]},
        ),
        "users": ("users", lambda row: dict(row)),
        "producers": ("producers", lambda row: dict(row)),
        "international_buyers": (
            "international_buyers",
            lambda row: {**row, "buyer_name": row["company_name"]},
        ),
        "municipalities": ("municipalities", lambda row: dict(row)),
        "farms": ("farms", lambda row: dict(row)),
        "farm_plots": ("farm_plots", lambda row: dict(row)),
        "harvest_deliveries": ("harvest_deliveries", lambda row: dict(row)),
        "export_batches": ("export_batches", lambda row: dict(row)),
        "batch_farm_compositions": ("batch_farm_compositions", lambda row: dict(row)),
        "buyer_batch_contracts": ("buyer_batch_contracts", lambda row: dict(row)),
        "cupping_evaluations": ("cupping_evaluations", lambda row: dict(row)),
        "farm_reserve_overlaps": ("farm_reserve_overlaps", lambda row: dict(row)),
    }
    projected: dict[str, list[dict[str, Any]]] = {}
    for source, (target, transform) in mappings.items():
        projected[target] = [
            {column: transform(row).get(column) for column in API_TABLES[target]}
            for row in dataset.get(source, [])
        ]
    return projected


def build_upsert_statement(table: str) -> Any:
    """Build the parametrised ``INSERT ... ON CONFLICT`` statement for one table."""
    from psycopg import sql

    columns = API_TABLES[table]
    conflict_target = CONFLICT_TARGETS[table]
    primary_key = PRIMARY_KEYS[table]
    # Never rewrite the PK (children reference it) nor the conflict key itself.
    update_columns = [
        column for column in columns if column != primary_key and column not in conflict_target
    ]
    if table in DO_NOTHING_TABLES or not update_columns:
        conflict_action = sql.SQL("DO NOTHING")
    else:
        conflict_action = sql.SQL("DO UPDATE SET {}").format(
            sql.SQL(", ").join(
                sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                for c in update_columns
            )
        )

    placeholders = []
    for column in columns:
        wrapper = _PLACEHOLDER_WRAPPERS.get((table, column))
        if wrapper:
            placeholders.append(sql.SQL(wrapper + "({})").format(sql.Placeholder()))
        else:
            placeholders.append(sql.Placeholder())

    return sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(placeholders),
        sql.SQL(", ").join(map(sql.Identifier, conflict_target)),
        conflict_action,
    )


def _upsert_rows(cursor: Any, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = API_TABLES[table]
    cursor.executemany(
        build_upsert_statement(table),
        [tuple(row[column] for column in columns) for row in rows],
    )


def is_test_database(dbname: str | None) -> bool:
    """Return whether the database name follows the test-database convention."""
    return bool(dbname) and dbname.endswith(TEST_DATABASE_SUFFIXES)


def assert_reset_allowed(dbname: str | None) -> None:
    """Refuse destructive resets unless the DB is a test DB or explicitly confirmed.

    A reset (``TRUNCATE ... CASCADE``) is allowed only when either:
    * the connected database name ends with ``_test_db``/``_test``
      (e.g. ``agrosense_test_db`` from postgres-docker.md), or
    * the environment variable ``SEED_RESET_CONFIRM_DB`` equals the exact name of
      the connected database (deliberate, per-database opt-in).
    """
    if is_test_database(dbname):
        return
    confirmed = os.getenv(RESET_CONFIRM_ENV, "")
    if dbname and confirmed == dbname:
        return
    raise ResetNotAllowedError(
        f"Reset (TRUNCATE CASCADE) rechazado sobre la base de datos {dbname!r}. "
        f"Solo se permite en bases de prueba (*_test_db) o si {RESET_CONFIRM_ENV} "
        "coincide exactamente con el nombre de la base de datos conectada."
    )


def assert_schema_ready(cursor: Any) -> None:
    """Fail fast if any API table is missing (API migrations not applied)."""
    cursor.execute(
        "SELECT t FROM unnest(%s::text[]) AS t WHERE to_regclass(t) IS NULL",
        (list(API_TABLES),),
    )
    missing = [row[0] for row in cursor.fetchall()]
    if missing:
        raise SchemaNotReadyError(
            "Faltan tablas del esquema de la API: "
            + ", ".join(missing)
            + ". Ejecuta primero `alembic upgrade head` desde el repositorio API."
        )


def write_api_dataset_with_connection(
    connection: Any,
    dataset: Mapping[str, list[dict[str, Any]]],
    *,
    reset: bool = False,
) -> dict[str, int]:
    """Persist projected data on an open connection, in foreign-key dependency order.

    The caller owns the transaction (commit/rollback). Returns rows sent per table.
    """
    from psycopg import sql

    projected = build_api_dataset(dataset)
    with connection.cursor() as cursor:
        assert_schema_ready(cursor)
        if reset:
            assert_reset_allowed(connection.info.dbname)
            tables = sql.SQL(", ").join(sql.Identifier(table) for table in reversed(API_TABLES))
            cursor.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(tables))
        for table, rows in projected.items():
            _upsert_rows(cursor, table, rows)
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('coffee_varieties', 'variety_id'), "
            "GREATEST(COALESCE((SELECT MAX(variety_id) FROM coffee_varieties), 1), 1), true)"
        )
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence('municipalities', 'municipality_id'), "
            "GREATEST(COALESCE((SELECT MAX(municipality_id) FROM municipalities), 1), 1), true)"
        )
    return {table: len(rows) for table, rows in projected.items()}


def normalize_database_url(database_url: str) -> str:
    """Convert SQLAlchemy-style URLs (``postgresql+psycopg://``) to libpq URLs."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def write_api_dataset(
    dataset: Mapping[str, list[dict[str, Any]]],
    database_url: str,
    *,
    reset: bool = False,
    connect: Callable[[str], Any] | None = None,
) -> dict[str, int]:
    """Persist projected data atomically (single transaction) into PostgreSQL."""
    if connect is None:
        import psycopg

        connect = psycopg.connect
    with connect(normalize_database_url(database_url)) as connection:
        return write_api_dataset_with_connection(connection, dataset, reset=reset)


def table_fingerprints(connection: Any) -> dict[str, tuple[int, str]]:
    """Return ``{table: (row_count, md5)}`` computed in SQL over the seeded columns.

    The MD5 checksum (seed-dataset-validation-criteria-en.md, CT-06) aggregates the
    text form of every seeded column ordered deterministically, excluding the
    server-managed ``created_at``/``updated_at`` audit columns.
    """
    from psycopg import sql

    fingerprints: dict[str, tuple[int, str]] = {}
    with connection.cursor() as cursor:
        for table, columns in API_TABLES.items():
            query = sql.SQL(
                "SELECT count(*), md5(coalesce(string_agg(r, '|' ORDER BY r), '')) "
                "FROM (SELECT ROW({})::text AS r FROM {}) AS t"
            ).format(
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.Identifier(table),
            )
            cursor.execute(query)
            count, checksum = cursor.fetchone()
            fingerprints[table] = (int(count), str(checksum))
    return fingerprints
