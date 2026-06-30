"""Tests for mesh generation."""

import numpy as np
import pytest

from map_generator.elevation import HeightField
from map_generator.mesh import MeshBuilder


def _make_heightfield(rows: int = 20, cols: int = 20, flat: bool = False) -> HeightField:
    """Create a synthetic HeightField for testing."""
    if flat:
        data = np.ones((rows, cols), dtype=np.float32) * 50
    else:
        x = np.linspace(-1, 1, cols)
        y = np.linspace(-1, 1, rows)
        xx, yy = np.meshgrid(x, y)
        data = (100 * (1 - (xx**2 + yy**2))).astype(np.float32)
        data = np.clip(data, 0, 100)
    return HeightField(
        data=data,
        north=10.0, south=5.0, east=20.0, west=15.0,
        crs="EPSG:4326", source="test", license="CC0", resolution_m=30,
    )


def test_mesh_builder_defaults():
    """MeshBuilder initialises with sensible defaults."""
    builder = MeshBuilder()
    assert builder.base_thickness_mm == 4.0
    assert builder.print_size_mm == 100.0
    assert builder.z_scale == 1.8


def test_mesh_has_vertices_and_faces():
    """Built mesh must have geometry."""
    mesh = MeshBuilder().build(_make_heightfield())
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0
    assert mesh.vertices.shape[1] == 3


def test_mesh_is_watertight_dome():
    """Dome-shaped heightfield produces a watertight mesh."""
    mesh = MeshBuilder().build(_make_heightfield(flat=False))
    assert mesh.is_watertight


def test_mesh_is_watertight_flat():
    """Flat heightfield also produces a watertight mesh."""
    mesh = MeshBuilder().build(_make_heightfield(flat=True))
    assert mesh.is_watertight


def test_mesh_volume_positive():
    """Watertight mesh volume should be positive (outward normals)."""
    mesh = MeshBuilder().build(_make_heightfield())
    assert mesh.is_watertight
    assert mesh.volume > 0


def test_mesh_z_scale():
    """Higher z_scale produces a taller mesh."""
    hf = _make_heightfield()
    low = MeshBuilder().build(hf, scale_z=1.0)
    high = MeshBuilder().build(hf, scale_z=3.0)
    assert high.vertices[:, 2].max() > low.vertices[:, 2].max()


def test_elevation_range_m():
    """elevation_range_m returns correct real-unit range."""
    data = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
    hf = HeightField(data=data, north=1, south=0, east=1, west=0,
                     crs="EPSG:4326", source="test", license="CC0", resolution_m=30)
    assert MeshBuilder().elevation_range_m(hf) == pytest.approx(30.0)
