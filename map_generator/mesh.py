"""Convert heightfield to a watertight 3D-printable mesh."""

from __future__ import annotations

import numpy as np
import trimesh

from .elevation import HeightField


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
