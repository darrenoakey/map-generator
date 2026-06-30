"""Command-line interface for map-generator."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import click

from .elevation import ElevationCache, HeightField, OpenMeteoSource, OpenTopographySource
from .mesh import MeshBuilder
from .url_parser import MapExtent, parse_google_maps_url


@click.group()
def cli() -> None:
    """map-generator: Google Maps URL → 3D-printable STL."""


@cli.command("generate")
@click.argument("url")
@click.option("-o", "--output", default="map.stl", help="Output STL filename.")
@click.option(
    "--source",
    type=click.Choice(["auto", "opentopography", "open-meteo"]),
    default="auto",
    help="Elevation source. 'auto' tries OpenTopography first.",
)
@click.option("--z-scale", type=float, default=1.8, help="Vertical exaggeration (default 1.8).")
@click.option("--base-mm", type=float, default=4.0, help="Base thickness in mm.")
@click.option("--print-mm", type=float, default=100.0, help="Physical footprint in mm.")
@click.option("--no-cache", is_flag=True, default=False, help="Skip elevation cache.")
@click.option("--verify", is_flag=True, default=False, help="Print detailed mesh validation.")
def generate(
    url: str,
    output: str,
    source: str,
    z_scale: float,
    base_mm: float,
    print_mm: float,
    no_cache: bool,
    verify: bool,
) -> None:
    """Convert a Google Maps URL to a 3D-printable STL.

    Example:

        map-generator generate 'https://www.google.com/maps/@-33.737,151.108,2934m'
    """
    _run_generate(url, output, source, z_scale, base_mm, print_mm, no_cache, verify)


@cli.command("inspect-url")
@click.argument("url")
def inspect_url(url: str) -> None:
    """Parse a Google Maps URL and print its extent without fetching elevation."""
    extent = parse_google_maps_url(url)
    north, south, east, west = extent.bbox_degrees()
    width_km = (east - west) * 111.32 * abs(math.cos(math.radians(extent.center_lat)))
    height_km = (north - south) * 111.0
    click.echo(f"Center:    {extent.center_lat:.6f}, {extent.center_lon:.6f}")
    click.echo(f"Altitude:  {extent.altitude_m:.0f} m")
    click.echo(f"Extent:    {width_km:.2f} km x {height_km:.2f} km")
    click.echo(f"BBox:      N {north:.6f}, S {south:.6f}, E {east:.6f}, W {west:.6f}")
    click.echo(f"Map type:  {extent.map_type}")


def main() -> None:
    """Entry point: if first non-flag arg looks like a URL, invoke 'generate'."""
    # Allow `map-generator <url> [opts]` without the 'generate' subcommand word.
    args = sys.argv[1:]
    subcommands = {"generate", "inspect-url", "--help", "-h", "--version"}
    if args and not args[0].startswith("-") and args[0] not in subcommands:
        sys.argv.insert(1, "generate")
    cli()


def _run_generate(
    url: str,
    output: str,
    source: str,
    z_scale: float,
    base_mm: float,
    print_mm: float,
    no_cache: bool,
    verify: bool,
) -> None:
    """Core pipeline: URL → elevation → mesh → STL + sidecar."""
    click.echo("Parsing Google Maps URL...")
    extent = parse_google_maps_url(url)
    click.echo(
        f"Center: {extent.center_lat:.6f}, {extent.center_lon:.6f}  "
        f"altitude {extent.altitude_m:.0f} m"
    )

    north, south, east, west = extent.bbox_degrees()
    ground_km = (north - south) * 111.0
    click.echo(f"Ground extent: ~{ground_km:.2f} km")

    cache = ElevationCache()
    heightfield: HeightField | None = None

    if not no_cache:
        click.echo("Checking elevation cache...")
        heightfield = cache.get(north, south, east, west)
        if heightfield:
            click.echo(f"  Loaded from cache (original source: {heightfield.license})")

    if heightfield is None:
        heightfield = _fetch_elevation(source, north, south, east, west)
        if not no_cache:
            cache.store(heightfield)
            click.echo("  Cached for future runs.")

    rows, cols = heightfield.data.shape
    click.echo(f"Elevation grid: {rows}x{cols} ({heightfield.resolution_m} m/sample)")

    builder = MeshBuilder(
        base_thickness_mm=base_mm,
        print_size_mm=print_mm,
        z_scale=z_scale,
    )
    elev_range_m = builder.elevation_range_m(heightfield)
    if elev_range_m < 20.0:
        click.echo(
            f"  Warning: low relief ({elev_range_m:.1f} m). "
            "Consider --z-scale 3.0+ for a more dramatic print."
        )

    click.echo("Building 3D mesh...")
    mesh = builder.build(heightfield)
    click.echo(
        f"  {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces, "
        f"watertight={mesh.is_watertight}"
    )

    if verify:
        _verify_mesh(mesh)

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out_path))
    click.echo(f"Saved STL: {out_path}")

    sidecar = _write_sidecar(out_path, extent, heightfield, rows, cols, z_scale, base_mm, print_mm)
    click.echo(f"Sidecar:   {sidecar}")

    preview = _write_preview(out_path, heightfield)
    click.echo(f"Preview:   {preview}")

    click.echo(f"License:   {heightfield.license}")


def _fetch_elevation(
    source: str,
    north: float,
    south: float,
    east: float,
    west: float,
) -> HeightField:
    """Fetch elevation; 'auto' tries OpenTopography then falls back to Open-Meteo."""
    if source in ("auto", "opentopography"):
        try:
            click.echo("Fetching elevation from OpenTopography (COP30)...")
            hf = OpenTopographySource().fetch(north, south, east, west)
            click.echo(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid.")
            return hf
        except Exception as exc:
            if source == "opentopography":
                raise
            click.echo(f"  OpenTopography unavailable ({exc}); falling back to Open-Meteo.")

    click.echo("Fetching elevation from Open-Meteo...")
    hf = OpenMeteoSource().fetch(north, south, east, west)
    click.echo(f"  {hf.data.shape[0]}x{hf.data.shape[1]} grid.")
    return hf


def _verify_mesh(mesh: object) -> None:
    """Print detailed mesh validation."""
    click.echo(f"  Watertight:  {mesh.is_watertight}")  # type: ignore[attr-defined]
    click.echo(f"  Winding CW:  {mesh.is_winding_consistent}")  # type: ignore[attr-defined]
    click.echo(f"  Volume:      {mesh.volume:.2f} mm3")  # type: ignore[attr-defined]
    click.echo(f"  Euler:       {mesh.euler_number}")  # type: ignore[attr-defined]


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
    ax.set_title(f"Elevation preview ({hf.source})")
    ax.axis("off")
    fig.savefig(str(preview_path), bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)
    return preview_path
