"""Convert heightfield to watertight 3D mesh."""

import numpy as np
import trimesh

from .elevation import HeightField


class MeshBuilder:
    """Convert a heightfield to a printable STL mesh."""

    def __init__(
        self,
        base_thickness_m: float = 10,
        wall_height_m: float = 5,
        smoothing_passes: int = 0,
    ):
        """Initialize mesh builder.

        Args:
            base_thickness_m: Thickness of the flat sealed bottom
            wall_height_m: Height of vertical walls around the perimeter
            smoothing_passes: Number of Laplacian smoothing iterations
        """
        self.base_thickness_m = base_thickness_m
        self.wall_height_m = wall_height_m
        self.smoothing_passes = smoothing_passes

    def build(self, heightfield: HeightField, scale_z: float = 1.0) -> trimesh.Trimesh:
        """Build watertight mesh from heightfield.

        Args:
            heightfield: HeightField with elevation data
            scale_z: Vertical exaggeration factor

        Returns:
            Watertight trimesh.Trimesh object
        """
        data = heightfield.data.astype(np.float32)

        # Normalize elevation to 0-1 range for consistent scaling
        h_min = np.nanmin(data)
        h_max = np.nanmax(data)
        if h_max > h_min:
            normalized = (data - h_min) / (h_max - h_min)
        else:
            normalized = np.zeros_like(data)

        # Apply vertical exaggeration
        normalized = normalized * scale_z

        rows, cols = data.shape
        base_z = -self.base_thickness_m

        # Create surface vertices
        x = np.arange(cols, dtype=np.float32)
        y = np.arange(rows, dtype=np.float32)
        xx, yy = np.meshgrid(x, y)

        vertices_top = np.column_stack(
            [xx.ravel(), yy.ravel(), normalized.ravel()]
        ).astype(np.float32)

        # Create base vertices (same x,y but at base_z)
        vertices_base = np.column_stack(
            [xx.ravel(), yy.ravel(), np.full(normalized.size, base_z, dtype=np.float32)]
        ).astype(np.float32)

        # Combine vertices: first all top, then all base
        vertices = np.vstack([vertices_top, vertices_base]).astype(np.float32)
        n_top = len(vertices_top)

        faces = []

        # Top surface faces
        for i in range(rows - 1):
            for j in range(cols - 1):
                v0 = i * cols + j
                v1 = i * cols + (j + 1)
                v2 = (i + 1) * cols + j
                v3 = (i + 1) * cols + (j + 1)

                faces.append([v0, v1, v2])
                faces.append([v1, v3, v2])

        # Vertical wall faces (connect top edges to base edges)
        # North edge
        for j in range(cols - 1):
            v_top_a = 0 * cols + j
            v_top_b = 0 * cols + (j + 1)
            v_base_a = n_top + 0 * cols + j
            v_base_b = n_top + 0 * cols + (j + 1)

            faces.append([v_top_a, v_top_b, v_base_b])
            faces.append([v_top_a, v_base_b, v_base_a])

        # South edge
        for j in range(cols - 1):
            v_top_a = (rows - 1) * cols + j
            v_top_b = (rows - 1) * cols + (j + 1)
            v_base_a = n_top + (rows - 1) * cols + j
            v_base_b = n_top + (rows - 1) * cols + (j + 1)

            faces.append([v_top_a, v_base_b, v_top_b])
            faces.append([v_top_a, v_base_a, v_base_b])

        # West edge
        for i in range(rows - 1):
            v_top_a = i * cols + 0
            v_top_b = (i + 1) * cols + 0
            v_base_a = n_top + i * cols + 0
            v_base_b = n_top + (i + 1) * cols + 0

            faces.append([v_top_a, v_top_b, v_base_b])
            faces.append([v_top_a, v_base_b, v_base_a])

        # East edge
        for i in range(rows - 1):
            v_top_a = i * cols + (cols - 1)
            v_top_b = (i + 1) * cols + (cols - 1)
            v_base_a = n_top + i * cols + (cols - 1)
            v_base_b = n_top + (i + 1) * cols + (cols - 1)

            faces.append([v_top_a, v_base_b, v_top_b])
            faces.append([v_top_a, v_base_a, v_base_b])

        # Bottom base faces (all top base vertices, reversed winding)
        for i in range(rows - 1):
            for j in range(cols - 1):
                v0 = n_top + i * cols + j
                v1 = n_top + i * cols + (j + 1)
                v2 = n_top + (i + 1) * cols + j
                v3 = n_top + (i + 1) * cols + (j + 1)

                faces.append([v0, v2, v1])
                faces.append([v1, v2, v3])

        faces = np.array(faces, dtype=np.uint32)

        # Create trimesh and ensure watertight
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)

        return mesh
