"""Building footprint sources: Microsoft Global ML Building Footprints, OSM."""

from __future__ import annotations

import csv
import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


@dataclass
class BuildingFootprint:
    """A single building footprint polygon with optional real height."""

    polygon: list[tuple[float, float]]  # (lat, lon) ring
    height_m: Optional[float]
    source: str  # "microsoft" or "osm"


def quadkey_for(lat: float, lon: float, zoom: int) -> str:
    """Convert lat/lon to a Bing/Microsoft tile quadkey at the given zoom."""
    sin_lat = math.sin(lat * math.pi / 180)
    x = (lon + 180) / 360
    y = 0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
    map_size = 256 << zoom
    pixel_x = min(max(x * map_size + 0.5, 0), map_size - 1)
    pixel_y = min(max(y * map_size + 0.5, 0), map_size - 1)
    tile_x, tile_y = int(pixel_x / 256), int(pixel_y / 256)

    digits = []
    for i in range(zoom, 0, -1):
        digit = 0
        mask = 1 << (i - 1)
        if tile_x & mask:
            digit += 1
        if tile_y & mask:
            digit += 2
        digits.append(str(digit))
    return "".join(digits)


def _bbox_corners(north: float, south: float, east: float, west: float):
    return [
        (north, west),
        (north, east),
        (south, west),
        (south, east),
        ((north + south) / 2, (east + west) / 2),
    ]


def _bbox_diagonal_km(north: float, south: float, east: float, west: float) -> float:
    """Great-circle-ish diagonal of the bbox in km (haversine on the corners)."""
    lat1, lon1 = math.radians(south), math.radians(west)
    lat2, lon2 = math.radians(north), math.radians(east)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


class MSBuildingFootprintSource:
    """Fetch real building footprints from Microsoft's Global ML Building
    Footprints dataset (free, no API key; ODbL-style attribution required).
    """

    LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
    ZOOM = 9
    MAX_TILES = 6
    # Each zoom-9 tile is tens of MB and covers a city-scale area (~tens of
    # km), so corner-sampled tile counting alone can't catch an oversized
    # request (a huge bbox can still land on only a handful of huge tiles).
    # Bound the actual geographic extent directly instead.
    MAX_DIAGONAL_KM = 50.0
    LICENSE = "Microsoft Global ML Building Footprints (ODbL)"

    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = Path(cache_dir or "~/.cache/map-generator/buildings").expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _links_path(self) -> Path:
        return self.cache_dir / "dataset-links.csv"

    def _links_for_quadkeys(self, quadkeys: set[str]) -> dict[str, str]:
        """Map each requested quadkey to its tile download URL."""
        links_path = self._links_path()
        if not links_path.exists():
            response = requests.get(self.LINKS_URL, timeout=120)
            response.raise_for_status()
            links_path.write_bytes(response.content)

        found: dict[str, str] = {}
        with open(links_path, newline="") as f:
            for row in csv.DictReader(f):
                qk = row.get("QuadKey", "")
                if qk in quadkeys:
                    found[qk] = row["Url"]
        return found

    def _tile_path(self, quadkey: str, url: str) -> Path:
        return self.cache_dir / f"tile_{quadkey}_{Path(url).name}"

    def _fetch_tile(self, quadkey: str, url: str) -> Path:
        path = self._tile_path(quadkey, url)
        if not path.exists():
            response = requests.get(url, timeout=300)
            response.raise_for_status()
            path.write_bytes(response.content)
        return path

    def fetch(self, north: float, south: float, east: float, west: float) -> list[BuildingFootprint]:
        """Fetch building footprints intersecting the bounding box."""
        diagonal_km = _bbox_diagonal_km(north, south, east, west)
        if diagonal_km > self.MAX_DIAGONAL_KM:
            raise ValueError(
                f"Requested extent is {diagonal_km:.0f} km across (max "
                f"{self.MAX_DIAGONAL_KM:.0f} km for building-footprint fetch); "
                "pass --radius-m to focus on a smaller area, or --no-buildings "
                "to skip footprints for a wide view."
            )
        quadkeys = {quadkey_for(lat, lon, self.ZOOM) for lat, lon in _bbox_corners(north, south, east, west)}
        if len(quadkeys) > self.MAX_TILES:
            raise ValueError(
                f"Requested extent spans {len(quadkeys)} building-footprint tiles "
                f"(max {self.MAX_TILES}); pass --radius-m to focus on a smaller area "
                "or --no-buildings to skip footprints for a wide view."
            )

        links = self._links_for_quadkeys(quadkeys)
        footprints: list[BuildingFootprint] = []
        for quadkey in quadkeys:
            url = links.get(quadkey)
            if not url:
                continue  # no buildings published for this tile (e.g. open water/desert)
            tile_path = self._fetch_tile(quadkey, url)
            footprints.extend(_parse_tile(tile_path, north, south, east, west))
        return footprints


def _parse_tile(path: Path, north: float, south: float, east: float, west: float) -> list[BuildingFootprint]:
    """Parse a gzipped GeoJSONL building tile, filtered to the bounding box."""
    footprints = []
    with gzip.open(path, "rt") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            feature = json.loads(line)
            ring = feature["geometry"]["coordinates"][0]
            lats = [point[1] for point in ring]
            lons = [point[0] for point in ring]
            centroid_lat = sum(lats) / len(lats)
            centroid_lon = sum(lons) / len(lons)
            if not (south <= centroid_lat <= north and west <= centroid_lon <= east):
                continue
            height = feature.get("properties", {}).get("height")
            footprints.append(
                BuildingFootprint(
                    polygon=[(lat, lon) for lon, lat in ring],
                    height_m=float(height) if height is not None and height > 0 else None,
                    source="microsoft",
                )
            )
    return footprints


class OSMBuildingSource:
    """Fetch building footprints from OpenStreetMap via the Overpass API
    (free, no API key required).
    """

    API_URLS = (
        "https://overpass-api.de/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
    )
    LICENSE = "OpenStreetMap contributors (ODbL)"

    def fetch(self, north: float, south: float, east: float, west: float) -> list[BuildingFootprint]:
        """Fetch building footprints intersecting the bounding box."""
        query = f'[out:json][timeout:25];way["building"]({south},{west},{north},{east});out geom;'
        last_error: requests.RequestException | None = None
        response: requests.Response | None = None
        for api_url in self.API_URLS:
            try:
                candidate = requests.post(
                    api_url,
                    data={"data": query},
                    headers={"User-Agent": "map-generator/0.1 (https://github.com/darrenoakey/map-generator)"},
                    timeout=30,
                )
                candidate.raise_for_status()
                response = candidate
                break
            except requests.RequestException as error:
                last_error = error
        if response is None:
            assert last_error is not None
            raise last_error
        elements = response.json().get("elements", [])

        footprints = []
        for element in elements:
            geometry = element.get("geometry")
            if not geometry:
                continue
            tags = element.get("tags", {})
            footprints.append(
                BuildingFootprint(
                    polygon=[(point["lat"], point["lon"]) for point in geometry],
                    height_m=_osm_height(tags),
                    source="osm",
                )
            )
        return footprints


def _osm_height(tags: dict) -> Optional[float]:
    """Derive a building height in metres from OSM tags, if present."""
    height = tags.get("height")
    if height:
        try:
            return float("".join(ch for ch in height if ch.isdigit() or ch == "."))
        except ValueError:
            pass
    levels = tags.get("building:levels")
    if levels:
        try:
            return float(levels) * 3.0
        except ValueError:
            pass
    return None


def fetch_buildings(
    north: float,
    south: float,
    east: float,
    west: float,
    source: str = "auto",
    cache_dir: Optional[str] = None,
) -> tuple[list[BuildingFootprint], str]:
    """Fetch real building footprints. Returns (footprints, provenance license).

    "auto" tries Microsoft's footprints first (broader real-world coverage)
    and falls back to OpenStreetMap if Microsoft has none for the area.
    """
    if source in ("auto", "microsoft"):
        ms_source = MSBuildingFootprintSource(cache_dir=cache_dir)
        footprints = ms_source.fetch(north, south, east, west)
        if footprints or source == "microsoft":
            return footprints, ms_source.LICENSE

    osm_source = OSMBuildingSource()
    footprints = osm_source.fetch(north, south, east, west)
    return footprints, osm_source.LICENSE
