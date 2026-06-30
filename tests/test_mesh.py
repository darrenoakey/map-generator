"""Tests for mesh generation."""

import numpy as np
import pytest
import trimesh

from map_generator.buildings import BuildingFootprint
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


def _square_footprint(center_lat: float, center_lon: float, half_deg: float, height_m) -> BuildingFootprint:
    """A small square footprint centred on (center_lat, center_lon)."""
    ring = [
        (center_lat - half_deg, center_lon - half_deg),
        (center_lat - half_deg, center_lon + half_deg),
        (center_lat + half_deg, center_lon + half_deg),
        (center_lat + half_deg, center_lon - half_deg),
        (center_lat - half_deg, center_lon - half_deg),
    ]
    return BuildingFootprint(polygon=ring, height_m=height_m, source="microsoft")


def test_build_buildings_places_extruded_solid():
    """A real footprint becomes a watertight extruded solid sitting on terrain."""
    hf = _make_heightfield(flat=True)  # bbox: north=10, south=5, east=20, west=15
    footprint = _square_footprint(center_lat=7.5, center_lon=17.5, half_deg=0.25, height_m=6.0)

    meshes, stats = MeshBuilder().build_buildings(hf, [footprint])

    assert stats.placed == 1
    assert stats.skipped_degenerate == 0
    assert stats.estimated_height_count == 0
    assert len(meshes) == 1
    assert meshes[0].is_watertight
    assert meshes[0].volume > 0


def test_build_buildings_sits_on_terrain_base():
    """The building's base should rest at the local terrain height, not float."""
    hf = _make_heightfield(flat=True)
    footprint = _square_footprint(center_lat=7.5, center_lon=17.5, half_deg=0.25, height_m=6.0)
    terrain = MeshBuilder().build(hf)

    meshes, _ = MeshBuilder().build_buildings(hf, [footprint])

    terrain_top_z = terrain.vertices[:, 2].max()  # flat terrain: top is uniform
    building_base_z = meshes[0].bounds[0][2]
    assert building_base_z == pytest.approx(terrain_top_z, abs=0.5)


def test_build_buildings_skips_degenerate_polygon():
    """A degenerate (collapsed) footprint is skipped, not silently fabricated."""
    hf = _make_heightfield(flat=True)
    degenerate = BuildingFootprint(
        polygon=[(7.5, 17.5)] * 4, height_m=6.0, source="microsoft"
    )

    meshes, stats = MeshBuilder().build_buildings(hf, [degenerate])

    assert meshes == []
    assert stats.placed == 0
    assert stats.skipped_degenerate == 1


def test_build_buildings_estimates_height_when_missing():
    """A footprint with no real height gets a flagged, honest default height."""
    hf = _make_heightfield(flat=True)
    footprint = _square_footprint(center_lat=7.5, center_lon=17.5, half_deg=0.25, height_m=None)

    meshes, stats = MeshBuilder().build_buildings(hf, [footprint])

    assert stats.placed == 1
    assert stats.estimated_height_count == 1
    assert meshes[0].is_watertight


def test_combined_terrain_and_buildings_mesh_stays_watertight():
    """Concatenating terrain + building solids preserves a printable, watertight scene."""
    hf = _make_heightfield(flat=False)
    footprints = [
        _square_footprint(center_lat=7.5, center_lon=17.5, half_deg=0.2, height_m=6.0),
        _square_footprint(center_lat=6.0, center_lon=16.0, half_deg=0.2, height_m=9.0),
    ]
    builder = MeshBuilder()
    terrain = builder.build(hf)
    building_meshes, stats = builder.build_buildings(hf, footprints)

    combined = trimesh.util.concatenate([terrain] + building_meshes)

    assert stats.placed == 2
    assert combined.is_watertight
    assert combined.volume > terrain.volume
