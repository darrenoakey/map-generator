"""Command-line interface for map-generator."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from .elevation import ElevationCache, HeightField, OpenMeteoSource
from .mesh import MeshBuilder
from .url_parser import MapExtent, parse_google_maps_url


def main() -> None:
    """Entry point: parse args and dispatch to appropriate handler."""
    # Handle implicit 'generate' when URL is first arg (map-generator <url>)
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-") and ("maps" in argv[0] or "http" in argv[0]):
        sys.argv = [sys.argv[0], "generate"] + argv

    parser = argparse.ArgumentParser(
        prog="map-generator",
        description="Convert Google Maps URLs to 3D-printable STL models",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="map-generator 0.1.0",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # generate subcommand
    gen_parser = subparsers.add_parser(
        "generate",
        help="Convert a Google Maps URL to STL",
    )
    gen_parser.add_argument("url", help="Google Maps URL")
    gen_parser.add_argument(
        "-o",
        "--output",
        default="map.stl",
        help="Output STL filename (default: map.stl)",
    )
    gen_parser.add_argument(
        "--z-scale",
        type=float,
        default=1.8,
        help="Vertical exaggeration factor (default: 1.8)",
    )
    gen_parser.add_argument(
        "--base-mm",
        type=float,
        default=4.0,
        help="Sealed base thickness in mm (default: 4.0)",
    )
    gen_parser.add_argument(
        "--print-mm",
        type=float,
        default=100.0,
        help="Physical footprint side length in mm (default: 100.0)",
    )
    gen_parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip elevation cache",
    )
    gen_parser.add_argument(
        "--verify",
        action="store_true",
        help="Print detailed mesh validation",
    )
    gen_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose output",
    )

    # inspect-url subcommand
    insp_parser = subparsers.add_parser(
        "inspect-url",
        help="Parse a Google Maps URL without fetching elevation",
    )
    insp_parser.add_argument("url", help="Google Maps URL")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "generate":
        _run_generate(
            args.url,
            args.output,
            args.z_scale,
            args.base_mm,
            args.print_mm,
            args.no_cache,
            args.verify,
            args.verbose,
        )
    elif args.command == "inspect-url":
        _inspect_url(args.url)


def _inspect_url(url: str) -> None:
    """Parse a Google Maps URL and print its extent."""
    try:
        extent = parse_google_maps_url(url)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    north, south, east, west = extent.bbox_degrees()
    width_km = (east - west) * 111.32 * abs(math.cos(math.radians(extent.center_lat)))
    height_km = (north - south) * 111.0

    print(f"Center:    {extent.center_lat:.6f}, {extent.center_lon:.6f}")
    print(f"Altitude:  {extent.altitude_m:.0f} m")
    print(f"Extent:    {width_km:.2f} km x {height_km:.2f} km")
    print(f"BBox:      N {north:.6f}, S {south:.6f}, E {east:.6f}, W {west:.6f}")
    print(f"Map type:  {extent.map_type}")


def _run_generate(
    url: str,
    output: str,
    z_scale: float,
    base_mm: float,
    print_mm: float,
    no_cache: bool,
    verify: bool,
    verbose: bool,
) -> None:
    """Core pipeline: URL → elevation → mesh → STL + sidecar."""
    try:
        if verbose:
            print("Parsing Google Maps URL...")
        extent = parse_google_maps_url(url)
        if verbose:
            print(
                f"Center: {extent.center_lat:.6f}, {extent.center_lon:.6f}  "
                f"altitude {extent.altitude_m:.0f} m"
            )

        north, south, east, west = extent.bbox_degrees()
        ground_km = (north - south) * 111.0
        if verbose:
            print(f"Ground extent: ~{ground_km:.2f} km")

        cache = ElevationCache()
        heightfield: HeightField | None = None

        if not no_cache:
            if verbose:
                print("Checking elevation cache...")
            heightfield = cache.get(north, south, east, west)
            if heightfield:
                if verbose:
                    print(f"  Loaded from cache (source: {heightfield.source})")

        if heightfield is None:
            if verbose:
                print("Fetching elevation from Open-Meteo...")
            heightfield = OpenMeteoSource().fetch(north, south, east, west)
            if verbose:
                print(f"  {heightfield.data.shape[0]}x{heightfield.data.shape[1]} grid")
            if not no_cache:
                cache.store(heightfield)
                if verbose:
                    print("  Cached for future runs")

        rows, cols = heightfield.data.shape
        if verbose:
            print(f"Elevation grid: {rows}x{cols} ({heightfield.resolution_m} m/sample)")

        builder = MeshBuilder(
            base_thickness_mm=base_mm,
            print_size_mm=print_mm,
            z_scale=z_scale,
        )
        elev_range_m = builder.elevation_range_m(heightfield)
        if elev_range_m < 20.0:
            print(
                f"Warning: low relief ({elev_range_m:.1f} m). "
                "Consider --z-scale 3.0+ for detail.",
                file=sys.stderr,
            )

        if verbose:
            print("Building 3D mesh...")
        mesh = builder.build(heightfield)
        if verbose:
            print(
                f"  {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces, "
                f"watertight={mesh.is_watertight}"
            )

        if verify:
            _verify_mesh(mesh)

        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        print(f"Saved STL: {out_path}")

        sidecar = _write_sidecar(out_path, extent, heightfield, rows, cols, z_scale, base_mm, print_mm)
        if verbose:
            print(f"Sidecar:   {sidecar}")

        if verbose:
            print(f"License:   {heightfield.license}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _verify_mesh(mesh: object) -> None:
    """Print detailed mesh validation."""
    print(f"  Watertight:  {mesh.is_watertight}")  # type: ignore[attr-defined]
    print(f"  Winding CW:  {mesh.is_winding_consistent}")  # type: ignore[attr-defined]
    print(f"  Volume:      {mesh.volume:.2f} mm3")  # type: ignore[attr-defined]
    print(f"  Euler:       {mesh.euler_number}")  # type: ignore[attr-defined]


def _write_sidecar(
    out_path: Path,
    extent: MapExtent,
    hf: HeightField,
    rows: int,
    cols: int,
    z_scale: float,
    base_mm: float,
    print_mm: float,
) -> Path:
    """Write JSON sidecar alongside the STL."""
    sidecar_path = out_path.with_suffix(".json")
    data = {
        "tool": "map-generator",
        "version": "0.1.0",
        "center_lat": extent.center_lat,
        "center_lon": extent.center_lon,
        "altitude_m": extent.altitude_m,
        "map_type": extent.map_type,
        "bbox": {
            "north": hf.north,
            "south": hf.south,
            "east": hf.east,
            "west": hf.west,
        },
        "elevation_source": hf.source,
        "elevation_resolution_m": hf.resolution_m,
        "elevation_license": hf.license,
        "grid_rows": rows,
        "grid_cols": cols,
        "z_scale": z_scale,
        "base_thickness_mm": base_mm,
        "print_size_mm": print_mm,
    }
    with open(sidecar_path, "w") as f:
        json.dump(data, f, indent=2)
    return sidecar_path
