"""Unit tests for PostGIS Geospatial and Forest Reserve Overlap Generator (DEF-06 / DEF-07).

Validates PostGIS ST_Intersects detection, polygon intersection generation,
overlap area calculation, and EUDR zero-deforestation compliance (RN-09, CA-08).
"""

from __future__ import annotations

from seed.spatial import PostGISSpatialGenerator, SpatialOverlapGenerator
from seed.spatial_models import SpatialOverlapResult
from seed.upsert_engine import UpsertEngine


def test_spatial_overlap_generator_intersection_detection():
    """Verify check_intersection correctly identifies overlapping, containing,
    and disjoint polygons.
    """
    gen = SpatialOverlapGenerator(seed=42)

    # Disjoint polygons
    poly_a = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)]
    poly_b = [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0), (5.0, 6.0), (5.0, 5.0)]
    assert gen.check_intersection(poly_a, poly_b) is False

    # Overlapping polygons (partial overlap)
    poly_c = [(0.5, 0.5), (1.5, 0.5), (1.5, 1.5), (0.5, 1.5), (0.5, 0.5)]
    assert gen.check_intersection(poly_a, poly_c) is True

    # Touching boundary
    poly_d = [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
    assert gen.check_intersection(poly_a, poly_d) is True


def test_force_overlap_polygon_guarantees_intersection():
    """Verify force_overlap_polygon places a farm polygon intersecting the target reserve."""
    spatial = PostGISSpatialGenerator(seed=42)
    overlap_gen = SpatialOverlapGenerator(seed=42)

    reserves = spatial.generate_forest_reserves(count=2)
    assert len(reserves) == 2
    target_reserve = reserves[0]

    farm_overlap = overlap_gen.force_overlap_polygon(
        farm_code="FIN-0099",
        name="Hacienda El Bosque",
        reserve=target_reserve,
        area_ha=12.0,
        sides=6,
    )

    assert farm_overlap.overlaps_reserve is True
    assert farm_overlap.is_valid_coords is True
    assert farm_overlap.wkt.startswith("POLYGON((")
    assert farm_overlap.ewkt.startswith("SRID=4326;POLYGON((")
    assert farm_overlap.geojson["type"] == "Polygon"

    # Strict geometric intersection test (simulates PostGIS ST_Intersects)
    is_intersecting = overlap_gen.check_intersection(farm_overlap.points, target_reserve.points)
    assert is_intersecting is True


def test_calculate_overlap_area_ha_bounds():
    """Verify overlap area calculation yields physically realistic bounded values."""
    gen = SpatialOverlapGenerator(seed=123)

    poly_farm = [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
    poly_reserve = [(1.0, 1.0), (5.0, 1.0), (5.0, 5.0), (1.0, 5.0), (1.0, 1.0)]

    farm_ha = 20.0
    reserve_ha = 500.0

    overlap_ha = gen.calculate_overlap_area_ha(
        farm_area_ha=farm_ha,
        reserve_area_ha=reserve_ha,
        farm_points=poly_farm,
        reserve_points=poly_reserve,
    )

    assert 0.1 <= overlap_ha <= farm_ha * 0.5
    # Zero/negative farm area fallback
    assert gen.calculate_overlap_area_ha(0.0, reserve_ha, poly_farm, poly_reserve) == 0.1


def test_create_overlap_record_attributes():
    """Verify SpatialOverlapResult creation, UUIDv5 determinism, and schema alignment."""
    gen = SpatialOverlapGenerator(seed=42)

    record = gen.create_overlap_record(
        farm_id="farm-uuid-001",
        farm_code="FIN-0001",
        reserve_id="res-uuid-001",
        reserve_code="RES-001",
        overlap_area_ha=2.45,
        defect_code="DEF-06",
    )

    assert isinstance(record, SpatialOverlapResult)
    assert record.farm_code == "FIN-0001"
    assert record.reserve_code == "RES-001"
    assert record.overlap_area_ha == 2.45
    assert record.deforestation_free_status == "NON_COMPLIANT"
    assert record.defect_code == "DEF-06"
    assert record.verified_at == "2026-10-13T05:00:00Z"

    # Schema dictionary export
    record_dict = record.to_dict()
    assert record_dict["overlap_id"] == record.overlap_id
    assert record_dict["farm_id"] == "farm-uuid-001"
    assert record_dict["reserve_id"] == "res-uuid-001"
    assert record_dict["overlap_area_ha"] == 2.45
    assert record_dict["deforestation_free_status"] == "NON_COMPLIANT"
    assert record_dict["defect_code"] == "DEF-06"


def test_generate_overlaps_for_dataset_orchestration():
    """Verify dataset-level spatial overlap generation and farm attribute
    mutation (RN-09, DEF-06).
    """
    spatial = PostGISSpatialGenerator(seed=99)

    overlap_gen = SpatialOverlapGenerator(seed=99)

    raw_reserves = spatial.generate_forest_reserves(count=3)
    reserves_data = [
        {
            "reserve_id": r.entity_id,
            "reserve_code": r.entity_code,
            "name": r.name,
            "area_ha": r.area_ha,
            "geom_ewkt": r.ewkt,
            "polygon_geojson": r.geojson,
        }
        for r in raw_reserves
    ]

    farms_data = [
        {
            "farm_id": f"farm-{i:03d}",
            "farm_code": f"FIN-{i:04d}",
            "name": f"Finca {i}",
            "total_area_ha": 15.0,
            "overlaps_reserve": False,
        }
        for i in range(10)
    ]

    # Generate with 30% overlap rate
    overlaps = overlap_gen.generate_overlaps_for_dataset(
        farms=farms_data,
        reserves=reserves_data,
        overlap_rate=0.30,
        defect_code="DEF-06",
    )

    assert len(overlaps) > 0
    assert all(o["deforestation_free_status"] == "NON_COMPLIANT" for o in overlaps)
    assert all(o["defect_code"] == "DEF-06" for o in overlaps)

    # Check affected farms are marked with overlaps_reserve = True and PostGIS EWKT
    overlapping_farms = [f for f in farms_data if f.get("overlaps_reserve")]
    assert len(overlapping_farms) == len(overlaps)
    for f in overlapping_farms:
        assert f["geom_ewkt"].startswith("SRID=4326;POLYGON((")
        assert f["polygon_geojson"]["type"] == "Polygon"
        assert f["deforestation_free_status"] == "NON_COMPLIANT"


def test_zero_overlap_rate_produces_no_overlaps():
    """Verify zero overlap rate produces clean nominal output with no defect injections."""
    overlap_gen = SpatialOverlapGenerator(seed=42)
    spatial = PostGISSpatialGenerator(seed=42)

    reserves = [
        {
            "reserve_id": r.entity_id,
            "reserve_code": r.entity_code,
            "geom_ewkt": r.ewkt,
            "polygon_geojson": r.geojson,
        }
        for r in spatial.generate_forest_reserves(count=2)
    ]
    farms = [
        {
            "farm_id": f"farm-{i}",
            "farm_code": f"FIN-{i:04d}",
            "total_area_ha": 10.0,
            "overlaps_reserve": False,
        }
        for i in range(5)
    ]

    overlaps = overlap_gen.generate_overlaps_for_dataset(
        farms=farms,
        reserves=reserves,
        overlap_rate=0.0,
    )
    assert overlaps == []
    assert all(f["overlaps_reserve"] is False for f in farms)


def test_upsert_engine_supports_farm_reserve_overlaps_table():
    """Verify UpsertEngine configures farm_reserve_overlaps table for idempotent loading."""
    from seed.upsert_engine import TABLE_UPSERT_REGISTRY

    assert "farm_reserve_overlaps" in TABLE_UPSERT_REGISTRY

    config = TABLE_UPSERT_REGISTRY["farm_reserve_overlaps"]
    assert config.table_name == "farm_reserve_overlaps"
    assert config.conflict_target == ("overlap_id",)

    engine = UpsertEngine()

    # Simulate generating SQL statement for an overlap record
    overlap_record = {
        "overlap_id": "78328b93-8fa9-556b-a25e-57df1e25e1aa",
        "farm_id": "a910901e-7b75-5807-b649-6561fc37ca5e",
        "reserve_id": "c3313a1e-8e89-53e7-a12e-998811223344",
        "overlap_area_ha": 1.75,
        "deforestation_free_status": "NON_COMPLIANT",
        "verified_at": "2026-10-13T05:00:00Z",
    }

    statements = engine.build_upsert_sql("farm_reserve_overlaps", [overlap_record])
    assert len(statements) == 1
    sql = statements[0]
    assert "INSERT INTO farm_reserve_overlaps" in sql
    assert "ON CONFLICT (overlap_id) DO NOTHING" in sql
