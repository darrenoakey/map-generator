"""Elevation data sources: OpenTopography, Open-Meteo fallback, local cache."""

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
import requests
from rasterio.io import MemoryFile


@dataclass
class HeightField:
    """2D elevation grid + provenance metadata."""

    data: np.ndarray  # Shape (rows, cols), dtype float32
    north: float
    south: float
    east: float
    west: float
    crs: str  # EPSG code, e.g., "EPSG:4326"
    source: str  # "opentopography", "open-meteo", "cache"
    license: str  # Attribution/license string
    resolution_m: float  # Approximate ground resolution in meters


class ElevationSource(ABC):
    """Abstract elevation data provider."""

    @abstractmethod
    def fetch(
        self, north: float, south: float, east: float, west: float
    ) -> HeightField:
        """Fetch elevation data for a bounding box."""
        pass


class OpenTopographySource(ElevationSource):
    """Fetch from OpenTopography Copernicus GLO-30 DEM."""

    API_URL = "https://cloud.sdsc.edu/v1/AUTH_opentopography/Raster/SRTM_GL30/SRTM_GL30_srtm"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with optional API key from keychain or env."""
        self.api_key = api_key or self._get_keychain_api_key()

    def _get_keychain_api_key(self) -> Optional[str]:
        """Retrieve API key from macOS Keychain."""
        import subprocess

        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    "map-generator-opentopography",
                    "-w",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def fetch(
        self, north: float, south: float, east: float, west: float
    ) -> HeightField:
        """Fetch elevation as GeoTIFF from OpenTopography."""
        if not self.api_key:
            raise ValueError(
                "OpenTopography API key required. "
                "Set via: security add-generic-password -s map-generator-opentopography -w <key>"
            )

        # OpenTopography expects north, south, east, west in degrees
        params = {
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            "outputFormat": "GeoTIFF",
            "API_KEY": self.api_key,
        }

        response = requests.get(self.API_URL, params=params, timeout=60)
        response.raise_for_status()

        # Parse the returned GeoTIFF
        with MemoryFile(response.content) as memfile:
            with memfile.open() as src:
                data = src.read(1).astype(np.float32)
                transform = src.transform
                height, width = data.shape

        return HeightField(
            data=data,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="opentopography",
            license="CC BY 4.0 (Copernicus DEM)",
            resolution_m=30,
        )


class OpenMeteoSource(ElevationSource):
    """Fetch elevation from Open-Meteo (free, keyless fallback)."""

    API_URL = "https://api.open-meteo.com/v1/elevation"

    def fetch(
        self, north: float, south: float, east: float, west: float
    ) -> HeightField:
        """Fetch elevation via grid sampling from Open-Meteo."""
        # Generate a reasonable grid within API limits (max ~100 points at once)
        grid_size = 15  # 15x15 = 225 points (but will make multiple requests)
        lat_samples = np.linspace(south, north, grid_size)
        lon_samples = np.linspace(west, east, grid_size)
        lats, lons = np.meshgrid(lat_samples, lon_samples, indexing="ij")

        # Flatten for API call
        lat_flat = lats.flatten()
        lon_flat = lons.flatten()

        # Split into chunks if too many points
        max_points = 100
        elevations_list = []

        for i in range(0, len(lat_flat), max_points):
            chunk_lats = lat_flat[i:i+max_points]
            chunk_lons = lon_flat[i:i+max_points]

            params = {
                "latitude": ",".join(f"{x:.4f}" for x in chunk_lats),
                "longitude": ",".join(f"{x:.4f}" for x in chunk_lons),
            }

            response = requests.get(self.API_URL, params=params, timeout=60)
            response.raise_for_status()
            result = response.json()

            elevations_list.extend(result.get("elevation", []))

        # Reshape to grid
        elevations = np.array(elevations_list, dtype=np.float32).reshape(lats.shape)

        return HeightField(
            data=elevations,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="open-meteo",
            license="CC0 (Open-Meteo)",
            resolution_m=1852,  # ~1/60 degree
        )


class ElevationCache:
    """Local cache for elevation data to avoid re-fetching."""

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = Path(cache_dir or "~/.cache/map-generator").expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _bbox_key(self, north: float, south: float, east: float, west: float) -> str:
        """Generate a cache key from bounding box."""
        # Round to 4 decimals for key stability
        return f"dem_{south:.4f}_{north:.4f}_{west:.4f}_{east:.4f}.json"

    def get(
        self, north: float, south: float, east: float, west: float
    ) -> Optional[HeightField]:
        """Retrieve cached elevation data if available."""
        key = self._bbox_key(north, south, east, west)
        cache_file = self.cache_dir / key
        if cache_file.exists():
            with open(cache_file) as f:
                meta = json.load(f)
            # Load numpy array from accompanying .npy file
            npy_file = cache_file.with_suffix(".npy")
            if npy_file.exists():
                data = np.load(npy_file)
                return HeightField(
                    data=data,
                    north=meta["north"],
                    south=meta["south"],
                    east=meta["east"],
                    west=meta["west"],
                    crs=meta["crs"],
                    source="cache",
                    license=meta["license"],
                    resolution_m=meta["resolution_m"],
                )
        return None

    def store(self, hf: HeightField) -> None:
        """Cache elevation data locally."""
        key = self._bbox_key(hf.north, hf.south, hf.east, hf.west)
        cache_file = self.cache_dir / key
        npy_file = cache_file.with_suffix(".npy")

        # Store metadata as JSON
        meta = {
            "north": hf.north,
            "south": hf.south,
            "east": hf.east,
            "west": hf.west,
            "crs": hf.crs,
            "license": hf.license,
            "resolution_m": hf.resolution_m,
            "source": hf.source,
        }
        with open(cache_file, "w") as f:
            json.dump(meta, f)

        # Store data as .npy
        np.save(npy_file, hf.data)
