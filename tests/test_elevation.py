"""Tests for elevation data sources."""

import tempfile

import numpy as np
import pytest

from map_generator.elevation import (
    ElevationCache,
    GoogleElevationSource,
    HeightField,
    OpenElevationSource,
    OpenMeteoSource,
    OpenTopographySource,
)


def test_heightfield_creation():
    """HeightField stores data and metadata correctly."""
    data = np.random.rand(30, 30).astype(np.float32)
    hf = HeightField(
        data=data,
        north=10.0,
        south=5.0,
        east=20.0,
        west=15.0,
        crs="EPSG:4326",
        source="test",
        license="CC0",
        resolution_m=30,
    )

    assert hf.data.shape == (30, 30)
    assert hf.north == 10.0
    assert hf.source == "test"


def test_elevation_cache_roundtrip():
    """Cached HeightField survives a store/get round-trip."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ElevationCache(tmpdir)

        data = np.arange(100, dtype=np.float32).reshape(10, 10)
        hf = HeightField(
            data=data,
            north=10.0,
            south=5.0,
            east=20.0,
            west=15.0,
            crs="EPSG:4326",
            source="opentopography",
            license="CC BY 4.0",
            resolution_m=30,
        )
        cache.store(hf)

        retrieved = cache.get(10.0, 5.0, 20.0, 15.0)
        assert retrieved is not None
        assert np.allclose(retrieved.data, data)
        assert retrieved.north == 10.0
        assert retrieved.source == "cache"


def test_elevation_cache_miss():
    """Cache miss returns None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ElevationCache(tmpdir)
        assert cache.get(10.0, 5.0, 20.0, 15.0) is None


@pytest.mark.network
def test_open_meteo_fetch():
    """Open-Meteo elevation API returns a grid_size×grid_size grid."""
    source = OpenMeteoSource(grid_size=5)  # 25 points, 1 chunk — minimises rate-limit risk
    # Small bounding box around Sydney Opera House
    hf = source.fetch(north=-33.85, south=-33.86, east=151.22, west=151.21)

    assert hf.data.shape == (5, 5)
    assert hf.source == "open-meteo"
    assert not np.all(np.isnan(hf.data))


@pytest.mark.network
def test_open_elevation_fetch():
    """Open-Elevation (the third, fully independent keyless fallback) returns
    a grid_size×grid_size grid for a real bounding box.
    """
    source = OpenElevationSource(grid_size=5)
    hf = source.fetch(north=-33.85, south=-33.86, east=151.22, west=151.21)

    assert hf.data.shape == (5, 5)
    assert hf.source == "open-elevation"
    assert not np.all(np.isnan(hf.data))


@pytest.mark.network
def test_google_elevation_fetch_near_warrawee_house():
    """Google Elevation API returns real, finer-resolution data for the
    actual house location (the corrected place-pin center, not the wide
    camera viewport — see test_url_parser.py).
    """
    try:
        source = GoogleElevationSource()
    except RuntimeError:
        pytest.skip("Google Elevation requires a key in the macOS Keychain")

    hf = source.fetch(north=-33.7355, south=-33.7382, east=151.1148, west=151.1114, grid_size=5)

    assert hf.data.shape == (5, 5)
    assert hf.source == "google"
    assert "Google" in hf.license
    assert not np.all(np.isnan(hf.data))
    # Real Sydney upper-north-shore elevation is well above sea level.
    assert 50 < float(np.nanmean(hf.data)) < 200


@pytest.mark.network
def test_opentopography_fetch():
    """OpenTopography COP30 returns a raster for the bounding box.

    Skipped when only the placeholder 'demo' key is available (requires real API key).
    """
    source = OpenTopographySource()
    if source.api_key == "demo":
        pytest.skip("OpenTopography requires a real API key (not 'demo')")

    # Small bounding box around Warrawee NSW
    hf = source.fetch(north=-33.73, south=-33.74, east=151.12, west=151.10)

    assert hf.source == "opentopography"
    assert hf.data.ndim == 2
    assert hf.data.shape[0] > 0 and hf.data.shape[1] > 0
    assert not np.all(np.isnan(hf.data))
    assert hf.resolution_m == 30
