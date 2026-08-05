"""Tests for building footprint sources."""

import gzip
from pathlib import Path

import pytest

from map_generator.buildings import (
    MSBuildingFootprintSource,
    OSMBuildingSource,
    _parse_tile,
    fetch_buildings,
    quadkey_for,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ms_buildings_warrawee_sample.jsonl"

# The real address from the Warrawee Google Maps URL (the place-pin, not the
# camera viewport — see test_url_parser.py).
HOUSE_LAT, HOUSE_LON = -33.7368471, 151.1131143


def test_quadkey_for_known_warrawee_point():
    """Empirically verified: this quadkey's tile contains real buildings
    ~32m from the house (confirmed by downloading the actual MS dataset
    tile and finding the nearest footprint at that distance).
    """
    assert quadkey_for(HOUSE_LAT, HOUSE_LON, zoom=9) == "311230132"


def test_parse_tile_filters_to_bbox(tmp_path):
    """Only footprints whose centroid falls in the bbox are returned."""
    gz_path = tmp_path / "tile.csv.gz"
    with gzip.open(gz_path, "wt") as out, open(FIXTURE) as src:
        out.write(src.read())

    # Tight bbox around the house excludes the one fixture row ~5km away.
    footprints = _parse_tile(gz_path, north=-33.735, south=-33.738, east=151.115, west=151.111)

    assert len(footprints) == 4
    assert all(f.source == "microsoft" for f in footprints)
    assert all(f.height_m is not None and f.height_m > 0 for f in footprints)
    # Each polygon round-trips as a list of (lat, lon) tuples.
    assert all(isinstance(point, tuple) and len(point) == 2 for f in footprints for point in f.polygon)


def test_parse_tile_excludes_far_building(tmp_path):
    """The far-away fixture row (>5km) is excluded by the bbox filter."""
    gz_path = tmp_path / "tile.csv.gz"
    with gzip.open(gz_path, "wt") as out, open(FIXTURE) as src:
        out.write(src.read())

    footprints = _parse_tile(gz_path, north=-33.730, south=-33.740, east=151.120, west=151.105)
    assert len(footprints) == 4  # not 5 — the far one stays out


@pytest.mark.network
def test_ms_building_source_finds_buildings_near_house():
    """End-to-end: the real Microsoft dataset has footprints near the house.

    A tight 150m-radius bbox proves real coverage exists at this address —
    OSM alone has none here (verified separately), which is why Microsoft is
    the primary source.
    """
    source = MSBuildingFootprintSource()
    footprints = source.fetch(
        north=HOUSE_LAT + 0.0014,
        south=HOUSE_LAT - 0.0014,
        east=HOUSE_LON + 0.0017,
        west=HOUSE_LON - 0.0017,
    )
    assert len(footprints) > 0
    assert all(f.source == "microsoft" for f in footprints)


@pytest.mark.network
def test_osm_building_source_fetch():
    """OSM building source returns real footprints for a covered suburb area."""
    source = OSMBuildingSource()
    # Wider Warrawee suburb bbox — confirmed to have OSM building coverage,
    # unlike the tight area immediately around this specific house.
    footprints = source.fetch(north=-33.728, south=-33.745, east=151.122, west=151.10)
    assert len(footprints) > 0
    assert all(f.source == "osm" for f in footprints)


@pytest.mark.network
def test_fetch_buildings_auto_uses_microsoft_for_house():
    """auto dispatch finds the real Microsoft footprints near the house."""
    footprints, license_text = fetch_buildings(
        north=HOUSE_LAT + 0.0014,
        south=HOUSE_LAT - 0.0014,
        east=HOUSE_LON + 0.0017,
        west=HOUSE_LON - 0.0017,
        source="auto",
    )
    assert len(footprints) > 0
    assert "Microsoft" in license_text


def test_ms_source_too_wide_extent_raises():
    """A geographically huge extent fails fast with an actionable message,
    before any network call — rather than silently downloading dozens of
    large (tens-of-MB) tile files.
    """
    source = MSBuildingFootprintSource()
    with pytest.raises(ValueError, match="radius-m"):
        source.fetch(north=-33.0, south=-34.5, east=152.0, west=150.5)
