"""Tests for elevation data sources."""

import tempfile

import numpy as np
import pytest

from map_generator.elevation import ElevationCache, HeightField, OpenMeteoSource


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
    """Open-Meteo elevation API returns a GRID_SIZE×GRID_SIZE grid."""
    source = OpenMeteoSource()
    # Small bounding box around Sydney Opera House
    hf = source.fetch(north=-33.85, south=-33.86, east=151.22, west=151.21)

    expected = OpenMeteoSource.GRID_SIZE
    assert hf.data.shape == (expected, expected)
    assert hf.source == "open-meteo"
    assert not np.all(np.isnan(hf.data))
