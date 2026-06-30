"""Parse Google Maps URLs to extract coordinates and bounding box."""

import math
import re
from dataclasses import dataclass


@dataclass
class MapExtent:
    """Coordinates and extent extracted from a Google Maps URL."""

    center_lat: float
    center_lon: float
    altitude_m: float
    map_type: str  # "3d" or "2d"

    @property
    def zoom_level(self) -> float:
        """Estimated zoom level from camera altitude (backward compat)."""
        return max(1.0, min(20.0, math.log2(40_075_000 / (self.altitude_m * 2))))

    def ground_extent_meters(self) -> float:
        """Estimate ground half-width in metres from camera altitude.

        Heuristic: ground_side ≈ altitude × 0.85.
        """
        return self.altitude_m * 0.85

    def bbox_degrees(self) -> tuple[float, float, float, float]:
        """Return (north, south, east, west) in decimal degrees."""
        half_m = self.ground_extent_meters() / 2.0
        half_lat = half_m / 111_000.0
        half_lon = half_m / (111_000.0 * math.cos(math.radians(self.center_lat)))
        return (
            self.center_lat + half_lat,
            self.center_lat - half_lat,
            self.center_lon + half_lon,
            self.center_lon - half_lon,
        )

    def bbox_meters(self) -> tuple[float, float, float, float]:
        """Alias for bbox_degrees (backward compat)."""
        return self.bbox_degrees()


def parse_google_maps_url(url: str) -> MapExtent:
    """Extract center coordinates and altitude from a Google Maps URL.

    Handles:
    - Place URLs: .../@lat,lon,<alt>m/...
    - Coord URLs: .../@lat,lon,<zoom>z/...
    """
    match = re.search(r"@([-\d.]+),([-\d.]+),([\d.]+)([zm])", url)
    if not match:
        raise ValueError(f"Could not parse Google Maps URL: {url!r}")

    lat_str, lon_str, value_str, unit = match.groups()
    center_lat = float(lat_str)
    center_lon = float(lon_str)
    value = float(value_str)

    if unit == "m":
        altitude_m = value
    else:
        # Zoom level → approximate altitude (inverse of zoom_level property)
        altitude_m = 40_075_000.0 / (2.0 ** (value + 1)) / 0.85

    map_type = "3d" if "data=!3m1!1e3" in url else "2d"
    return MapExtent(
        center_lat=center_lat,
        center_lon=center_lon,
        altitude_m=altitude_m,
        map_type=map_type,
    )
