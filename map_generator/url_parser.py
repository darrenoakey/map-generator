"""Parse Google Maps URLs to extract coordinates and extent."""

import re
from dataclasses import dataclass


@dataclass
class MapExtent:
    """Bounding box and metadata extracted from a Google Maps URL."""

    center_lat: float
    center_lon: float
    zoom_level: float  # from URL; informs extent
    map_type: str  # "3d" or "2d"

    def ground_extent_meters(self) -> float:
        """Estimate ground extent in meters from zoom level.

        Rough approximation: at zoom 15 (~1.5km), zoom 20 (~30m).
        """
        # At zoom z, ~40075km / 2^z gives approx meters per tile
        # We'll use a simpler model based on the zoom level
        base_extent = 2000  # meters at zoom 10
        return base_extent / (2 ** (self.zoom_level - 10))

    def bbox_meters(self) -> tuple[float, float, float, float]:
        """Return (north, south, east, west) in degrees, roughly centered.

        For simplicity, compute a square extent in degrees using rough conversion.
        1 degree latitude ≈ 111 km.
        """
        extent_meters = self.ground_extent_meters()
        extent_deg = extent_meters / (111 * 1000)  # Convert meters to degrees
        north = self.center_lat + extent_deg / 2
        south = self.center_lat - extent_deg / 2
        east = self.center_lon + extent_deg / 2
        west = self.center_lon - extent_deg / 2
        return (north, south, east, west)


def parse_google_maps_url(url: str) -> MapExtent:
    """Extract coordinates and zoom from a Google Maps URL.

    Supports:
    - Place URLs: /place/.../@lat,lon,Zm/...
    - Coordinates URLs: /@lat,lon,Zm/...
    - Altitude zoom: /@lat,lon,<meters>m/...
    """
    # Pattern: @lat,lon,<number>[z|m] (m = meters altitude, z = zoom level)
    match = re.search(r'@([-\d.]+),([-\d.]+),(\d+)[zm]', url)
    if match:
        lat, lon, zoom_or_alt = match.groups()
        center_lat = float(lat)
        center_lon = float(lon)
        # For altitude in meters, estimate zoom level (roughly)
        alt_meters = float(zoom_or_alt)
        # Estimate zoom from altitude: zoom ≈ log2(40075000 / (altitude * 2))
        import math
        if alt_meters > 100:  # Likely altitude in meters
            zoom_level = max(1, min(20, math.log2(40075000 / (alt_meters * 2))))
        else:
            zoom_level = float(zoom_or_alt)

        map_type = "3d" if "data=!3m1!1e3" in url else "2d"
        return MapExtent(
            center_lat=center_lat,
            center_lon=center_lon,
            zoom_level=zoom_level,
            map_type=map_type,
        )

    raise ValueError(f"Could not parse Google Maps URL: {url}")
