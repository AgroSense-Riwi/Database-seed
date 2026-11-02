"""DEF-07 forest-reserve overlaps built from real spatial intersections."""

from __future__ import annotations

import pytest
from shapely import wkt as shapely_wkt
from shapely.geometry import Polygon, shape

from seed.faker_generators import (
    AgroSenseFakerGenerator,
    select_reserve_overlap_farms,
)
from seed.spatial_geometry import polygon_intersection, ring_area_ha


@pytest.fixture(scope="module")
def dev_dataset():
    return AgroSenseFakerGenerator(seed=42).generate_all(mode="dev")


def test_selection_follows_def07_rate_of_pilot_farms():
    assert select_reserve_overlap_farms(130, 30) == [8, 23]  # 5% of 30 -> 2
    prod = select_reserve_overlap_farms(1300, 300)
    assert len(prod) == 15  # 5% of 300
    assert all(1 <= n <= 300 for n in prod)
    assert select_reserve_overlap_farms(10, 0) == []
    assert select_reserve_overlap_farms(10, 5) == [3]  # at least one when pilots exist
    assert select_reserve_overlap_farms(130, 30) == select_reserve_overlap_farms(130, 30)


def test_overlap_flags_match_geometry_and_rate(dev_dataset):
    farms = dev_dataset["farms"]
    overlaps = dev_dataset["farm_reserve_overlaps"]
    flagged = {f["farm_id"] for f in farms if f["overlaps_reserve"]}
    assert flagged == {o["farm_id"] for o in overlaps}
    expected = {farms[n - 1]["farm_id"] for n in select_reserve_overlap_farms(130, 30)}
    assert flagged == expected
    pilots = {f["farm_id"] for f in farms if f["has_pilot_sensors"]}
    assert flagged <= pilots


def test_overlap_geometry_is_the_real_intersection(dev_dataset):
    farms = {f["farm_id"]: f for f in dev_dataset["farms"]}
    reserves = {r["reserve_id"]: r for r in dev_dataset["forest_reserves"]}
    for overlap in dev_dataset["farm_reserve_overlaps"]:
        farm = farms[overlap["farm_id"]]
        reserve = reserves[overlap["reserve_id"]]
        assert overlap["reserve_name"] == reserve["name"]

        ewkt = overlap["overlap_geometry"]
        assert ewkt.startswith("SRID=4326;POLYGON((")
        geom = shapely_wkt.loads(ewkt.split(";", 1)[1])
        assert geom.is_valid and geom.area > 0

        farm_poly = shape(farm["polygon_geojson"])
        reserve_poly = shape(reserve["polygon_geojson"])
        expected = farm_poly.intersection(reserve_poly)
        # Same shape up to the 1e-6 deg coordinate rounding.
        assert geom.symmetric_difference(expected).area < 1e-3 * expected.area
        # Not the whole farm polygon: the farm straddles the reserve boundary.
        assert geom.area < farm_poly.area

        area = ring_area_ha([tuple(p) for p in geom.exterior.coords])
        assert overlap["overlap_area_ha"] == pytest.approx(round(area, 2))
        assert 0 < overlap["overlap_area_ha"] < farm["total_area_ha"]


def test_non_overlapping_farms_do_not_touch_any_reserve(dev_dataset):
    reserves = [shape(r["polygon_geojson"]) for r in dev_dataset["forest_reserves"]]
    for farm in dev_dataset["farms"]:
        if farm["overlaps_reserve"]:
            continue
        poly = shape(farm["polygon_geojson"])
        assert not any(poly.intersects(r) for r in reserves), farm["farm_code"]


def test_ring_area_ha_matches_generated_area():
    gen = AgroSenseFakerGenerator(seed=7)
    polygon = gen.spatial_gen.generate_farm_polygon("FIN-0001", "Finca Test", area_ha=12.5)
    assert ring_area_ha(polygon.points) == pytest.approx(12.5, rel=0.01)


def test_polygon_intersection_helper():
    square = [(0.0, 0.0), (0.002, 0.0), (0.002, 0.002), (0.0, 0.002), (0.0, 0.0)]
    shifted = [(0.001, 0.001), (0.003, 0.001), (0.003, 0.003), (0.001, 0.003), (0.001, 0.001)]
    far = [(1.0, 1.0), (1.002, 1.0), (1.002, 1.002), (1.0, 1.002), (1.0, 1.0)]

    inter = polygon_intersection(square, shifted)
    assert inter is not None
    assert Polygon(inter).area == pytest.approx(0.001 * 0.001)
    # 0.001 deg x 0.001 deg at the equator ~ 111.139 m x 111.139 m ~ 1.235 ha
    assert ring_area_ha(inter) == pytest.approx(1.2352, rel=1e-3)
    assert polygon_intersection(square, far) is None


def test_overlaps_are_deterministic():
    a = AgroSenseFakerGenerator(seed=42).generate_all(mode="dev", farms_count=40, pilot_count=40)
    b = AgroSenseFakerGenerator(seed=42).generate_all(mode="dev", farms_count=40, pilot_count=40)
    assert a["farm_reserve_overlaps"] == b["farm_reserve_overlaps"]
    assert len(a["farm_reserve_overlaps"]) >= 2
