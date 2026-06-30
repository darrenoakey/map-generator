"""Convert heightfield to a watertight 3D-printable mesh."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from shapely.geometry import Polygon

from .buildings import BuildingFootprint
from .elevation import HeightField

# Used only when a footprint carries no real height (e.g. an OSM building with
# no height/levels tag). Typical Australian single-storey house. Always
# reported separately in BuildingPlacementStats so callers can disclose it
# honestly rather than presenting it as measured data.
DEFAULT_BUILDING_HEIGHT_M = 6.0

# Minimum visible solid height, so a real but tiny structure (e.g. a shed)
# doesn't vanish into a sub-printable sliver at small print sizes.
MIN_BUILDING_HEIGHT_MM = 1.0

# Footprints smaller than this (in mm^2 at print scale) are treated as
# degenerate/noise rather than a real printable building.
MIN_FOOTPRINT_AREA_MM2 = 0.5


@dataclass
class BuildingPlacementStats:
    """Outcome of placing a batch of building footprints onto the mesh."""

    placed: int
    skipped_degenerate: int
    estimated_height_count: int


class MeshBuilder:
    """Convert a HeightField to a watertight STL-ready Trimesh."""

    def __init__(
        self,
        base_thickness_mm: float = 4.0,
        print_size_mm: float = 100.0,
        z_scale: float = 1.8,
        # Legacy alias kept for backward compat
        base_thickness_m: float | None = None,
    ):
        """Initialise mesh builder.

        Args:
            base_thickness_mm: Sealed flat base thickness in mm.
            print_size_mm: Physical footprint side length in mm.
            z_scale: Vertical exaggeration factor.
        """
        if base_thickness_m is not None:
            base_thickness_mm = base_thickness_m
        self.base_thickness_mm = base_thickness_mm
        self.print_size_mm = print_size_mm
        self.z_scale = z_scale

    def build(
        self, heightfield: HeightField, scale_z: float | None = None
    ) -> trimesh.Trimesh:
        """Build a watertight mesh from elevation data.

        Args:
            heightfield: Source elevation data.
            scale_z: Override instance z_scale if provided.

        Returns:
            Watertight trimesh.Trimesh with consistent outward normals.
        """
        scale = scale_z if scale_z is not None else self.z_scale
        data = heightfield.data.astype(np.float32)

        rows, cols = data.shape
        z_norm = _normalize(data)
        height_range_mm = 20.0 * scale

        dx = self.print_size_mm / max(cols - 1, 1)
        dy = self.print_size_mm / max(rows - 1, 1)
        z_top = z_norm * height_range_mm
        base_z = -self.base_thickness_mm

        vertices, faces = _build_geometry(rows, cols, dx, dy, z_top, base_z)
        return trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

    def elevation_range_m(self, heightfield: HeightField) -> float:
        """Return real elevation range from the heightfield in metres."""
        data = heightfield.data.astype(np.float32)
        return float(np.nanmax(data) - np.nanmin(data))

    def build_buildings(
        self,
        heightfield: HeightField,
        footprints: list[BuildingFootprint],
        scale_z: float | None = None,
    ) -> tuple[list[trimesh.Trimesh], BuildingPlacementStats]:
        """Extrude real building footprints into solids sitting on the terrain.

        Each footprint becomes its own watertight prism, scaled vertically by
        the same metres-per-mm factor the terrain uses (so a building reads as
        a building relative to the terrain relief, not an arbitrary height),
        and translated so its base meets the local terrain surface. A
        footprint with no real height uses DEFAULT_BUILDING_HEIGHT_M, counted
        separately in the returned stats so callers can disclose it honestly.
        Degenerate footprints (collapsed or too small to print) are skipped,
        never fabricated.
        """
        scale = scale_z if scale_z is not None else self.z_scale
        data = heightfield.data.astype(np.float32)
        rows, cols = data.shape
        z_norm = _normalize(data)
        height_range_mm = 20.0 * scale
        dx = self.print_size_mm / max(cols - 1, 1)
        dy = self.print_size_mm / max(rows - 1, 1)
        z_top = z_norm * height_range_mm

        elev_range_m = self.elevation_range_m(heightfield)
        mm_per_metre = height_range_mm / elev_range_m if elev_range_m > 1e-6 else height_range_mm / 20.0

        meshes: list[trimesh.Trimesh] = []
        placed = 0
        skipped_degenerate = 0
        estimated_height_count = 0

        for footprint in footprints:
            local_xy = [
                _latlon_to_local_mm(lat, lon, heightfield, self.print_size_mm)
                for lat, lon in footprint.polygon
            ]
            polygon = _clean_polygon(local_xy)
            if polygon is None:
                skipped_degenerate += 1
                continue

            estimated = footprint.height_m is None
            height_m = DEFAULT_BUILDING_HEIGHT_M if footprint.height_m is None else footprint.height_m
            height_mm = max(height_m * mm_per_metre, MIN_BUILDING_HEIGHT_MM)

            centroid = polygon.centroid
            base_z = _sample_terrain_z(z_top, rows, cols, dx, dy, centroid.x, centroid.y)

            building = trimesh.creation.extrude_polygon(polygon, height=height_mm)
            building.apply_translation([0, 0, base_z])

            meshes.append(building)
            placed += 1
            if estimated:
                estimated_height_count += 1

        stats = BuildingPlacementStats(
            placed=placed,
            skipped_degenerate=skipped_degenerate,
            estimated_height_count=estimated_height_count,
        )
        return meshes, stats


def _normalize(data: np.ndarray) -> np.ndarray:
    """Normalize elevation to [0, 1]; all-zero for flat terrain."""
    h_min = np.nanmin(data)
    h_max = np.nanmax(data)
    if h_max > h_min:
        return (data - h_min) / (h_max - h_min)
    return np.zeros_like(data, dtype=np.float32)


def _build_geometry(
    rows: int,
    cols: int,
    dx: float,
    dy: float,
    z_top: np.ndarray,
    base_z: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Build (vertices, faces) for a watertight terrain solid.

    Vertex layout:
    - 0 .. rows*cols-1: top surface.
    - rows*cols .. 2*rows*cols-1: base (same x,y at base_z).
    """
    n_top = rows * cols

    ix = np.arange(cols, dtype=np.float32) * dx
    iy = np.arange(rows, dtype=np.float32) * dy
    gx, gy = np.meshgrid(ix, iy)

    top_verts = np.column_stack([gx.ravel(), gy.ravel(), z_top.ravel()])
    base_verts = np.column_stack(
        [gx.ravel(), gy.ravel(), np.full(n_top, base_z, dtype=np.float32)]
    )
    vertices = np.vstack([top_verts, base_verts]).astype(np.float32)

    faces = (
        _top_faces(rows, cols)
        + _bottom_faces(rows, cols, n_top)
        + _wall_north(cols, n_top)
        + _wall_south(rows, cols, n_top)
        + _wall_west(rows, cols, n_top)
        + _wall_east(rows, cols, n_top)
    )

    return vertices, np.array(faces, dtype=np.int64)


def _top_faces(rows: int, cols: int) -> list[list[int]]:
    """Top terrain, outward normal +Z."""
    faces = []
    for i in range(rows - 1):
        for j in range(cols - 1):
            v00 = i * cols + j
            v10 = i * cols + j + 1
            v01 = (i + 1) * cols + j
            v11 = (i + 1) * cols + j + 1
            faces.append([v00, v10, v01])
            faces.append([v10, v11, v01])
    return faces


def _bottom_faces(rows: int, cols: int, n_top: int) -> list[list[int]]:
    """Flat base, outward normal -Z (reversed winding of top)."""
    faces = []
    for i in range(rows - 1):
        for j in range(cols - 1):
            v00 = n_top + i * cols + j
            v10 = n_top + i * cols + j + 1
            v01 = n_top + (i + 1) * cols + j
            v11 = n_top + (i + 1) * cols + j + 1
            faces.append([v00, v01, v10])
            faces.append([v10, v01, v11])
    return faces


def _wall_north(cols: int, n_top: int) -> list[list[int]]:
    """North wall (row 0), outward normal -Y."""
    faces = []
    for j in range(cols - 1):
        t0, t1 = j, j + 1
        b0, b1 = n_top + j, n_top + j + 1
        faces.append([t0, b0, t1])
        faces.append([t1, b0, b1])
    return faces


def _wall_south(rows: int, cols: int, n_top: int) -> list[list[int]]:
    """South wall (last row), outward normal +Y."""
    faces = []
    for j in range(cols - 1):
        t0 = (rows - 1) * cols + j
        t1 = (rows - 1) * cols + j + 1
        b0 = n_top + (rows - 1) * cols + j
        b1 = n_top + (rows - 1) * cols + j + 1
        faces.append([t0, t1, b0])
        faces.append([t1, b1, b0])
    return faces


def _wall_west(rows: int, cols: int, n_top: int) -> list[list[int]]:
    """West wall (column 0), outward normal -X."""
    faces = []
    for i in range(rows - 1):
        t0 = i * cols
        t1 = (i + 1) * cols
        b0 = n_top + i * cols
        b1 = n_top + (i + 1) * cols
        faces.append([t0, t1, b0])
        faces.append([t1, b1, b0])
    return faces


def _wall_east(rows: int, cols: int, n_top: int) -> list[list[int]]:
    """East wall (last column), outward normal +X."""
    faces = []
    for i in range(rows - 1):
        t0 = i * cols + (cols - 1)
        t1 = (i + 1) * cols + (cols - 1)
        b0 = n_top + i * cols + (cols - 1)
        b1 = n_top + (i + 1) * cols + (cols - 1)
        faces.append([t0, b0, t1])
        faces.append([t1, b0, b1])
    return faces


def _latlon_to_local_mm(
    lat: float, lon: float, heightfield: HeightField, print_size_mm: float
) -> tuple[float, float]:
    """Project a (lat, lon) into the same local mm grid the terrain mesh uses.

    Matches _build_geometry's affine mapping exactly: x increases west→east,
    y increases south→north, both spanning [0, print_size_mm] across the
    heightfield's bbox.
    """
    lon_span = heightfield.east - heightfield.west
    lat_span = heightfield.north - heightfield.south
    x_mm = (lon - heightfield.west) / lon_span * print_size_mm if lon_span else 0.0
    y_mm = (lat - heightfield.south) / lat_span * print_size_mm if lat_span else 0.0
    return x_mm, y_mm


def _clean_polygon(points: list[tuple[float, float]]) -> Polygon | None:
    """Build a valid, non-degenerate shapely Polygon from local mm points.

    Returns None for footprints too small or malformed to print: fewer than 3
    distinct vertices, self-intersecting beyond repair, or below the minimum
    printable area.
    """
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area < MIN_FOOTPRINT_AREA_MM2:
        return None
    if polygon.geom_type != "Polygon":
        # buffer(0) on a bowtie can yield a MultiPolygon; take the largest part.
        parts = list(polygon.geoms)  # type: ignore[attr-defined]
        largest = max(parts, key=lambda geom: geom.area)
        if largest.area < MIN_FOOTPRINT_AREA_MM2:
            return None
        polygon = largest
    return polygon


def _sample_terrain_z(
    z_top: np.ndarray, rows: int, cols: int, dx: float, dy: float, x_mm: float, y_mm: float
) -> float:
    """Bilinear-sample the terrain top surface height at a local (x, y) in mm."""
    col_f = np.clip(x_mm / dx if dx else 0.0, 0, cols - 1)
    row_f = np.clip(y_mm / dy if dy else 0.0, 0, rows - 1)
    col0, row0 = int(np.floor(col_f)), int(np.floor(row_f))
    col1, row1 = min(col0 + 1, cols - 1), min(row0 + 1, rows - 1)
    fx, fy = col_f - col0, row_f - row0

    z00, z10 = z_top[row0, col0], z_top[row0, col1]
    z01, z11 = z_top[row1, col0], z_top[row1, col1]
    z0 = z00 * (1 - fx) + z10 * fx
    z1 = z01 * (1 - fx) + z11 * fx
    return float(z0 * (1 - fy) + z1 * fy)
