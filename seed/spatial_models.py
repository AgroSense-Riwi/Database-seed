"""Shared spatial types and coordinate bounds for seed geometry generation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

COFFEE_REGION_BOUNDS = {
    "min_lat": 1.0,
    "max_lat": 7.5,
    "min_lon": -77.5,
    "max_lon": -74.5,
}

COLOMBIA_VALID_BOUNDS = {
    "min_lat": -4.23,
    "max_lat": 13.50,
    "min_lon": -81.73,
    "max_lon": -66.85,
}

AGROSENSE_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


@dataclass(frozen=True)
class SpatialPolygonResult:
    """Generated polygon with coordinates and PostGIS/GeoJSON representations."""

    entity_id: str
    entity_code: str
    name: str
    center_lat: float
    center_lon: float
    area_ha: float
    points: list[tuple[float, float]]
    wkt: str
    geojson: dict[str, Any]
    is_valid_coords: bool
    overlaps_reserve: bool = False
    srid: int = 4326

    @property
    def ewkt(self) -> str:
        """Return EWKT accepted by PostGIS ``ST_GeomFromEWKT``."""
        return f"SRID={self.srid};{self.wkt}"


@dataclass(frozen=True)
class SpatialOverlapResult:
    """Record representing a spatial intersection between a farm and a forest reserve.

    Models PostGIS ST_Intersects detection (RN-09, CA-08, DEF-06/DEF-07).
    """

    overlap_id: str
    farm_id: str
    farm_code: str
    reserve_id: str
    reserve_code: str
    overlap_area_ha: float
    deforestation_free_status: str = "NON_COMPLIANT"
    defect_code: str = "DEF-06"
    verified_at: str = "2026-10-13T05:00:00Z"

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary matching farm_reserve_overlaps table schema."""
        return {
            "overlap_id": self.overlap_id,
            "farm_id": self.farm_id,
            "reserve_id": self.reserve_id,
            "overlap_area_ha": self.overlap_area_ha,
            "deforestation_free_status": self.deforestation_free_status,
            "defect_code": self.defect_code,
            "verified_at": self.verified_at,
        }
