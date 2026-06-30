"""Tests for mesh generation."""

import numpy as np
import pytest

from map_generator.elevation import HeightField
from map_generator.mesh import MeshBuilder


def test_mesh_builder_init():
    """Test MeshBuilder initialization."""
    builder = MeshBuilder(base_thickness_m=10, wall_height_m=5)
    assert builder.base_thickness_m == 10
    assert builder.wall_height_m == 5


def test_mesh_build():
    """Test building a mesh from a heightfield."""
    # Create a simple dome heightfield
    rows, cols = 20, 20
    x = np.linspace(-1, 1, cols)
    y = np.linspace(-1, 1, rows)
    xx, yy = np.meshgrid(x, y)
    data = (100 * (1 - (xx**2 + yy**2))).astype(np.float32)
    data = np.clip(data, 0, 100)

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

    builder = MeshBuilder()
    mesh = builder.build(hf, scale_z=1.0)

    # Check mesh properties
    assert len(mesh.vertices) > 0
    assert len(mesh.faces) > 0
    assert mesh.vertices.shape[1] == 3  # (x, y, z)
    assert mesh.is_watertight


def test_mesh_is_watertight():
    """Test that generated meshes are watertight."""
    # Create a simple flat heightfield
    data = np.ones((10, 10), dtype=np.float32) * 50

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

    builder = MeshBuilder()
    mesh = builder.build(hf)

    assert mesh.is_watertight
