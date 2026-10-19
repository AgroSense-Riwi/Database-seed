"""Projection and PostgreSQL writer for the API's operational schema."""

from __future__ import annotations

from collections.abc import Mapping
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
}

_PRIMARY_KEYS = {
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
}


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
    }
    projected: dict[str, list[dict[str, Any]]] = {}
    for source, (target, transform) in mappings.items():
        projected[target] = [
            {column: transform(row).get(column) for column in API_TABLES[target]}
            for row in dataset.get(source, [])
        ]
    return projected


def _upsert_rows(cursor: Any, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    from psycopg import sql

    columns = API_TABLES[table]
    primary_key = _PRIMARY_KEYS[table]
    update_columns = [column for column in columns if column != primary_key]
    updates = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
        for column in update_columns
    )
    conflict_action = (
        sql.SQL("DO UPDATE SET {}").format(updates) if updates else sql.SQL("DO NOTHING")
    )
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        sql.Identifier(primary_key),
        conflict_action,
    )
    cursor.executemany(statement, [tuple(row[column] for column in columns) for row in rows])


def write_api_dataset(
    dataset: Mapping[str, list[dict[str, Any]]], database_url: str, *, reset: bool = False
) -> None:
    """Persist projected data atomically, in foreign-key dependency order."""
    import psycopg
    from psycopg import sql

    projected = build_api_dataset(dataset)
    connection_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(connection_url) as connection:
        with connection.cursor() as cursor:
            if reset:
                tables = sql.SQL(", ").join(
                    sql.Identifier(table) for table in reversed(API_TABLES)
                )
                cursor.execute(
                    sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE").format(tables)
                )
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