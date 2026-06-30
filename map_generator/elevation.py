"""Elevation data sources: Open-Meteo with local cache."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import requests


@dataclass
class HeightField:
    """2D elevation grid + provenance metadata."""

    data: np.ndarray  # Shape (rows, cols), dtype float32
    north: float
    south: float
    east: float
    west: float
    crs: str  # EPSG code, e.g., "EPSG:4326"
    source: str  # "open-meteo" or "cache"
    license: str  # Attribution/license string
    resolution_m: float  # Approximate ground resolution in meters


class OpenMeteoSource:
    """Fetch elevation from Open-Meteo (free, no API key required)."""

    API_URL = "https://api.open-meteo.com/v1/elevation"
    GRID_SIZE = 30  # default: 30x30 = 900 points, chunked 100 at a time

    def __init__(self, grid_size: int = 30):
        self.GRID_SIZE = grid_size

    def fetch(
        self, north: float, south: float, east: float, west: float
    ) -> HeightField:
        """Fetch elevation grid via Open-Meteo point queries."""
        lat_samples = np.linspace(south, north, self.GRID_SIZE)
        lon_samples = np.linspace(west, east, self.GRID_SIZE)
        lats, lons = np.meshgrid(lat_samples, lon_samples, indexing="ij")

        lat_flat = lats.flatten()
        lon_flat = lons.flatten()

        # Chunk into batches of 100 to stay within URL length limits
        max_points = 100
        elevations_list = []

        for i in range(0, len(lat_flat), max_points):
            chunk_lats = lat_flat[i : i + max_points]
            chunk_lons = lon_flat[i : i + max_points]

            params = {
                "latitude": ",".join(f"{x:.4f}" for x in chunk_lats),
                "longitude": ",".join(f"{x:.4f}" for x in chunk_lons),
            }

            # Retry on 429 with exponential backoff
            response = None
            for attempt in range(6):
                response = requests.get(self.API_URL, params=params, timeout=60)
                if response.status_code != 429:
                    break
                wait = 5 * (2 ** attempt)
                time.sleep(wait)
            if response is None or response.status_code == 429:
                raise RuntimeError("Open-Meteo elevation API rate limit; retry later.")
            response.raise_for_status()

            result = response.json()
            elevations_list.extend(result.get("elevation", []))
            # Delay between chunks to avoid rate limits
            if i + max_points < len(lat_flat):
                time.sleep(1.0)

        elevations = np.array(elevations_list, dtype=np.float32).reshape(lats.shape)

        return HeightField(
            data=elevations,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="open-meteo",
            license="Open-Meteo elevation (CC0)",
            resolution_m=90,
        )


class ElevationCache:
    """Local disk cache for elevation data."""

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize cache, defaulting to ~/.cache/map-generator."""
        self.cache_dir = Path(cache_dir or "~/.cache/map-generator").expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _bbox_key(self, north: float, south: float, east: float, west: float) -> str:
        """Generate a stable cache key from the bounding box."""
        return f"dem_{south:.4f}_{north:.4f}_{west:.4f}_{east:.4f}.json"

    def get(
        self, north: float, south: float, east: float, west: float
    ) -> Optional[HeightField]:
        """Return cached HeightField if available, else None."""
        key = self._bbox_key(north, south, east, west)
        cache_file = self.cache_dir / key
        npy_file = cache_file.with_suffix(".npy")
        if not (cache_file.exists() and npy_file.exists()):
            return None
        with open(cache_file) as f:
            meta = json.load(f)
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

    def store(self, hf: HeightField) -> None:
        """Persist a HeightField to disk."""
        key = self._bbox_key(hf.north, hf.south, hf.east, hf.west)
        cache_file = self.cache_dir / key
        npy_file = cache_file.with_suffix(".npy")
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
        np.save(npy_file, hf.data)
