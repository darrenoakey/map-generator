"""Command-line interface for map-generator."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import trimesh

from .buildings import fetch_buildings
from .elevation import (
    ElevationCache,
    GoogleElevationSource,
    HeightField,
    OpenElevationSource,
    OpenMeteoSource,
    OpenTopographySource,
)
from .mesh import BuildingPlacementStats, MeshBuilder
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
        "--source",
        choices=["auto", "google", "opentopography", "open-meteo", "open-elevation"],
        default="auto",
        help="Elevation source: auto tries Google (if a key is configured), then "
        "OpenTopography, then Open-Meteo, then Open-Elevation (default: auto)",
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
        "--radius-m",
        type=float,
        default=None,
        help="Override the ground extent half-width in metres (default: derived "
        "from camera altitude). Use a small value (e.g. 150-300) to focus on a "
        "single property and its immediate neighbours.",
    )
    gen_parser.add_argument(
        "--buildings",
        dest="buildings",
        action="store_true",
        default=True,
        help="Extrude real building footprints onto the terrain (default: on)",
    )
    gen_parser.add_argument(
        "--no-buildings",
        dest="buildings",
        action="store_false",
        help="Skip building footprints; terrain only",
    )
    gen_parser.add_argument(
        "--building-source",
        choices=["auto", "microsoft", "osm"],
        default="auto",
        help="Building footprint source: auto tries Microsoft's dataset first, "
        "falling back to OpenStreetMap (default: auto)",
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
        _run_generate(args)
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


def _fetch_elevation(
    source: str,
    north: float,
    south: float,
    east: float,
    west: float,
    verbose: bool,
) -> HeightField:
    """Fetch elevation. auto cascades Google (best resolution, needs a billed
    API key) -> OpenTopography (30 m, needs a real API key) -> Open-Meteo
    (90 m, keyless) -> Open-Elevation (SRTM, keyless) — two independent
    keyless fallbacks so one source's shared daily quota running out doesn't
    block the tool entirely.
    """
    if source in ("auto", "google"):
        try:
            if verbose:
                print("Fetching elevation from Google Maps Platform...")
            hf = GoogleElevationSource().fetch(north, south, east, west)
            if verbose:
                print(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid at {hf.resolution_m:.1f} m/px")
            return hf
        except Exception as exc:
            if source == "google":
                raise
            print(
                f"Google Elevation unavailable ({exc}); falling back to OpenTopography.",
                file=sys.stderr,
            )

    if source in ("auto", "opentopography"):
        try:
            if verbose:
                print("Fetching elevation from OpenTopography (COP30)...")
            hf = OpenTopographySource().fetch(north, south, east, west)
            if verbose:
                print(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid at {hf.resolution_m} m/px")
            return hf
        except Exception as exc:
            if source == "opentopography":
                raise
            print(
                f"OpenTopography unavailable ({exc}); falling back to Open-Meteo.",
                file=sys.stderr,
            )

    if source in ("auto", "open-meteo"):
        try:
            if verbose:
                print("Fetching elevation from Open-Meteo...")
            hf = OpenMeteoSource().fetch(north, south, east, west)
            if verbose:
                print(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid at {hf.resolution_m} m/px")
            return hf
        except Exception as exc:
            if source == "open-meteo":
                raise
            print(
                f"Open-Meteo unavailable ({exc}); falling back to Open-Elevation.",
                file=sys.stderr,
            )

    if verbose:
        print("Fetching elevation from Open-Elevation...")
    hf = OpenElevationSource().fetch(north, south, east, west)
    if verbose:
        print(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid at {hf.resolution_m} m/px")
    return hf


def _run_generate(args: argparse.Namespace) -> None:
    """Core pipeline: URL → elevation → buildings → mesh → STL + sidecar + preview."""
    try:
        if args.verbose:
            print("Parsing Google Maps URL...")
        extent = parse_google_maps_url(args.url)
        if args.verbose:
            print(f"Center: {extent.center_lat:.6f}, {extent.center_lon:.6f}  altitude {extent.altitude_m:.0f} m")

        north, south, east, west = _resolve_bbox(extent, args.radius_m)
        ground_km = (north - south) * 111.0
        if args.verbose:
            print(f"Ground extent: ~{ground_km:.2f} km")

        cache = ElevationCache()
        heightfield: HeightField | None = None

        if not args.no_cache:
            if args.verbose:
                print("Checking elevation cache...")
            heightfield = cache.get(north, south, east, west)
            if heightfield and args.verbose:
                print(f"  Loaded from cache (original source: {heightfield.license})")

        if heightfield is None:
            heightfield = _fetch_elevation(args.source, north, south, east, west, args.verbose)
            if not args.no_cache:
                cache.store(heightfield)
                if args.verbose:
                    print("  Cached for future runs")

        rows, cols = heightfield.data.shape
        if args.verbose:
            print(f"Elevation grid: {rows}x{cols} ({heightfield.resolution_m} m/sample)")

        builder = MeshBuilder(
            base_thickness_mm=args.base_mm,
            print_size_mm=args.print_mm,
            z_scale=args.z_scale,
        )
        elev_range_m = builder.elevation_range_m(heightfield)
        if elev_range_m < 20.0:
            print(
                f"Warning: low relief ({elev_range_m:.1f} m). Consider --z-scale 3.0+ for detail.",
                file=sys.stderr,
            )

        if args.verbose:
            print("Building terrain mesh...")
        mesh = builder.build(heightfield)

        building_license = ""
        building_stats: BuildingPlacementStats | None = None
        if args.buildings:
            building_license, building_stats, mesh = _add_buildings(
                builder, heightfield, north, south, east, west, args.building_source, args.verbose, mesh
            )

        if args.verbose:
            print(f"  {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces, watertight={mesh.is_watertight}")

        if args.verify:
            _verify_mesh(mesh)

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out_path))
        print(f"Saved STL: {out_path}")

        sidecar = _write_sidecar(
            out_path,
            extent,
            heightfield,
            rows,
            cols,
            args.z_scale,
            args.base_mm,
            args.print_mm,
            building_stats,
            building_license,
        )
        print(f"Sidecar:   {sidecar}")

        preview = _write_preview(out_path, heightfield)
        print(f"Preview:   {preview}")

        print(f"Elevation license: {heightfield.license}")
        if building_stats is not None:
            print(f"Building license:  {building_license}")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _resolve_bbox(extent: MapExtent, radius_m: float | None) -> tuple[float, float, float, float]:
    """Resolve the fetch bounding box: --radius-m overrides the altitude heuristic."""
    if radius_m is None:
        return extent.bbox_degrees()
    half_lat = radius_m / 111_000.0
    half_lon = radius_m / (111_000.0 * math.cos(math.radians(extent.center_lat)))
    return (
        extent.center_lat + half_lat,
        extent.center_lat - half_lat,
        extent.center_lon + half_lon,
        extent.center_lon - half_lon,
    )


def _add_buildings(
    builder: MeshBuilder,
    heightfield: HeightField,
    north: float,
    south: float,
    east: float,
    west: float,
    building_source: str,
    verbose: bool,
    mesh: trimesh.Trimesh,
) -> tuple[str, BuildingPlacementStats, trimesh.Trimesh]:
    """Fetch real building footprints and extrude them onto the mesh."""
    if verbose:
        print("Fetching building footprints...")
    try:
        footprints, building_license = fetch_buildings(north, south, east, west, source=building_source)
    except ValueError as exc:
        print(f"Warning: skipping buildings ({exc})", file=sys.stderr)
        return "", BuildingPlacementStats(0, 0, 0), mesh

    if not footprints:
        print(
            "Warning: no real building footprints found in this area; terrain only.",
            file=sys.stderr,
        )
        return building_license, BuildingPlacementStats(0, 0, 0), mesh

    building_meshes, stats = builder.build_buildings(heightfield, footprints)
    if verbose:
        print(
            f"  {stats.placed} buildings placed ({building_license}); "
            f"{stats.skipped_degenerate} skipped, "
            f"{stats.estimated_height_count} used an estimated height"
        )
    if building_meshes:
        mesh = trimesh.util.concatenate([mesh] + building_meshes)
    return building_license, stats, mesh


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
    building_stats: BuildingPlacementStats | None,
    building_license: str,
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
        "buildings": (
            None
            if building_stats is None
            else {
                "placed": building_stats.placed,
                "skipped_degenerate": building_stats.skipped_degenerate,
                "estimated_height_count": building_stats.estimated_height_count,
                "license": building_license,
            }
        ),
    }
    with open(sidecar_path, "w") as f:
        json.dump(data, f, indent=2)
    return sidecar_path


def _write_preview(out_path: Path, hf: HeightField) -> Path:
    """Write hillshade preview PNG alongside the STL."""
    import numpy as np

    preview_path = out_path.with_suffix(".png")
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return preview_path

    data = hf.data.astype(np.float32)
    fig, ax = plt.subplots(figsize=(6, 6), dpi=100)
    ax.imshow(data, origin="lower", cmap="terrain", interpolation="nearest")
    ax.set_title(f"Elevation preview ({hf.source}, {hf.resolution_m} m/px)")
    ax.axis("off")
    fig.savefig(str(preview_path), bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return preview_path
