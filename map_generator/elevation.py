"""Elevation data sources: OpenTopography, Open-Meteo fallback, local cache."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import requests
from daz_secrets import Client, DazSecretsError, ErrorCode


def _credential(service: str) -> Optional[str]:
    try:
        return Client().get(service, "api-key").value.decode("utf-8")
    except DazSecretsError as error:
        if error.code is ErrorCode.NOT_FOUND:
            return None
        raise RuntimeError(f"Cannot read {service}/api-key credential") from error
    except UnicodeDecodeError as error:
        raise RuntimeError(f"Invalid UTF-8 in {service}/api-key credential") from error


@dataclass
class HeightField:
    """2D elevation grid + provenance metadata."""

    data: np.ndarray  # Shape (rows, cols), dtype float32
    north: float
    south: float
    east: float
    west: float
    crs: str  # EPSG code, e.g., "EPSG:4326"
    source: str  # "opentopography", "open-meteo", or "cache"
    license: str  # Attribution/license string
    resolution_m: float  # Approximate ground resolution in meters


class GoogleElevationSource:
    """Fetch elevation from the Google Maps Platform Elevation API.

    Requires a billed Google Cloud project with the Elevation API enabled
    and an API key in the daz-secrets provider. Unlike the open DEM sources, this
    data is used under Google Maps Platform's commercial Terms of Service,
    not a CC/ODbL license — callers must attribute "Powered by Google" per
    https://cloud.google.com/maps-platform/terms.
    """

    API_URL = "https://maps.googleapis.com/maps/api/elevation/json"
    TOS_NOTICE = "Google Maps Platform Elevation API — Powered by Google (see Maps Platform ToS)"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _credential("map-generator-google-maps")
        if not self.api_key:
            raise RuntimeError(
                "Google Elevation API requires map-generator-google-maps/api-key in daz-secrets"
            )

    def fetch(self, north: float, south: float, east: float, west: float, grid_size: int = 30) -> HeightField:
        """Fetch an elevation grid via Google's batched point-elevation lookup."""
        lat_samples = np.linspace(south, north, grid_size)
        lon_samples = np.linspace(west, east, grid_size)
        lats, lons = np.meshgrid(lat_samples, lon_samples, indexing="ij")
        lat_flat, lon_flat = lats.flatten(), lons.flatten()

        max_points = 300
        elevations_list: list[float] = []
        resolutions: list[float] = []

        for i in range(0, len(lat_flat), max_points):
            chunk_lats = lat_flat[i : i + max_points]
            chunk_lons = lon_flat[i : i + max_points]
            locations = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in zip(chunk_lats, chunk_lons))

            response = requests.get(self.API_URL, params={"locations": locations, "key": self.api_key}, timeout=60)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "OK":
                raise RuntimeError(
                    f"Google Elevation API error: {payload.get('status')} {payload.get('error_message', '')}"
                )
            for point in payload["results"]:
                elevations_list.append(point["elevation"])
                resolutions.append(point.get("resolution", 30.0))

        elevations = np.array(elevations_list, dtype=np.float32).reshape(lats.shape)

        return HeightField(
            data=elevations,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="google",
            license=self.TOS_NOTICE,
            resolution_m=max(resolutions) if resolutions else 30.0,
        )


class OpenTopographySource:
    """Fetch Copernicus GLO-30 DEM (~30 m) from OpenTopography API."""

    API_URL = "https://portal.opentopography.org/API/globaldem"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _credential("map-generator-opentopography") or "demo"

    def fetch(self, north: float, south: float, east: float, west: float) -> HeightField:
        """Fetch COP30 GeoTIFF for bounding box and return HeightField."""
        from rasterio.io import MemoryFile  # type: ignore[import-untyped]

        params = {
            "demtype": "COP30",
            "south": south,
            "north": north,
            "west": west,
            "east": east,
            "outputFormat": "GTiff",
            "API_Key": self.api_key,
        }
        response = requests.get(self.API_URL, params=params, timeout=120)
        response.raise_for_status()

        content = response.content
        if content[:5] in (b"<?xml", b"<html", b"<HTML"):
            raise ValueError(f"OpenTopography API error: {content.decode(errors='replace')[:300]}")

        with MemoryFile(content) as memfile:
            with memfile.open() as src:
                data = src.read(1).astype(np.float32)

        # Replace nodata sentinel (-9999 typical) with NaN then fill via nearest neighbour
        data[data < -1000] = np.nan
        if np.any(np.isnan(data)):
            from scipy.ndimage import distance_transform_edt

            nan_mask = np.isnan(data)
            # distance_transform_edt operates on the "background" (False pixels),
            # so invert: find the nearest valid (non-NaN) cell for each NaN cell.
            _, indices = distance_transform_edt(  # type: ignore[misc]
                nan_mask,
                return_distances=True,
                return_indices=True,
            )
            # indices shape: (2, rows, cols) — row and col of nearest valid cell
            row_idx, col_idx = indices[0], indices[1]
            data[nan_mask] = data[row_idx[nan_mask], col_idx[nan_mask]]
            data = data.astype(np.float32)

        return HeightField(
            data=data,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="opentopography",
            license="Copernicus DEM GLO-30 (CC BY 4.0)",
            resolution_m=30,
        )


class OpenMeteoSource:
    """Fetch elevation from Open-Meteo (free, no API key required)."""

    API_URL = "https://api.open-meteo.com/v1/elevation"
    GRID_SIZE = 30  # default: 30x30 = 900 points, chunked 100 at a time

    def __init__(self, grid_size: int = 30):
        self.GRID_SIZE = grid_size

    def fetch(self, north: float, south: float, east: float, west: float) -> HeightField:
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
                wait = 5 * (2**attempt)
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


class OpenElevationSource:
    """Fetch elevation from Open-Elevation (free, no API key; SRTM-based).

    Used as a last-resort fallback when Open-Meteo's shared daily request
    quota is exhausted — a real, observed failure mode (their API returns
    "Daily API request limit exceeded" once exceeded, not a transient 429),
    so a single keyless source isn't enough for reliability.
    """

    API_URL = "https://api.open-elevation.com/api/v1/lookup"
    GRID_SIZE = 30

    def __init__(self, grid_size: int = 30):
        self.GRID_SIZE = grid_size

    def fetch(self, north: float, south: float, east: float, west: float) -> HeightField:
        """Fetch elevation grid via Open-Elevation's bulk POST lookup."""
        lat_samples = np.linspace(south, north, self.GRID_SIZE)
        lon_samples = np.linspace(west, east, self.GRID_SIZE)
        lats, lons = np.meshgrid(lat_samples, lon_samples, indexing="ij")

        lat_flat = lats.flatten()
        lon_flat = lons.flatten()

        max_points = 300
        elevations_list = []

        for i in range(0, len(lat_flat), max_points):
            chunk_lats = lat_flat[i : i + max_points]
            chunk_lons = lon_flat[i : i + max_points]
            locations = [{"latitude": float(lat), "longitude": float(lon)} for lat, lon in zip(chunk_lats, chunk_lons)]

            response = None
            for attempt in range(4):
                response = requests.post(self.API_URL, json={"locations": locations}, timeout=60)
                if response.status_code != 429:
                    break
                time.sleep(5 * (2**attempt))
            if response is None or response.status_code == 429:
                raise RuntimeError("Open-Elevation API rate limit; retry later.")
            response.raise_for_status()

            result = response.json()
            elevations_list.extend(point["elevation"] for point in result.get("results", []))

        elevations = np.array(elevations_list, dtype=np.float32).reshape(lats.shape)

        return HeightField(
            data=elevations,
            north=north,
            south=south,
            east=east,
            west=west,
            crs="EPSG:4326",
            source="open-elevation",
            license="Open-Elevation (SRTM-based, public domain)",
            resolution_m=30,
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

    def get(self, north: float, south: float, east: float, west: float) -> Optional[HeightField]:
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
