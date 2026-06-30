"""Command-line interface for map-generator."""

import click

from .elevation import ElevationCache, OpenMeteoSource, OpenTopographySource
from .mesh import MeshBuilder
from .url_parser import parse_google_maps_url


@click.command()
@click.argument("url")
@click.option(
    "-o",
    "--output",
    default="map.stl",
    help="Output STL filename",
)
@click.option(
    "--source",
    type=click.Choice(["opentopography", "open-meteo"]),
    default="opentopography",
    help="Elevation data source",
)
@click.option(
    "--scale-z",
    type=float,
    default=1.0,
    help="Vertical exaggeration factor",
)
@click.option(
    "--base-thickness",
    type=float,
    default=10.0,
    help="Thickness of sealed base in mm",
)
@click.option(
    "--wall-height",
    type=float,
    default=5.0,
    help="Height of perimeter walls in mm",
)
def main(
    url: str,
    output: str,
    source: str,
    scale_z: float,
    base_thickness: float,
    wall_height: float,
) -> None:
    """Convert a Google Maps URL to a 3D-printable STL.

    Example:
        map-generator 'https://www.google.com/maps/place/32+Mitchell+Cres...'
    """
    click.echo("Parsing Google Maps URL...")
    extent = parse_google_maps_url(url)
    click.echo(
        f"Center: {extent.center_lat:.4f}, {extent.center_lon:.4f} "
        f"(zoom {extent.zoom_level})"
    )

    # Get bounding box
    north, south, east, west = extent.bbox_meters()
    click.echo(f"Extent: {north:.4f}°N - {south:.4f}°S, {west:.4f}°W - {east:.4f}°E")

    # Try cache first
    click.echo("Checking elevation cache...")
    cache = ElevationCache()
    heightfield = cache.get(north, south, east, west)

    if heightfield:
        click.echo(f"Loaded from cache ({heightfield.source})")
    else:
        # Fetch elevation data
        click.echo(f"Fetching elevation data from {source}...")
        if source == "opentopography":
            elevation_source = OpenTopographySource()
        else:
            elevation_source = OpenMeteoSource()

        heightfield = elevation_source.fetch(north, south, east, west)
        click.echo(f"Downloaded {heightfield.data.shape} grid ({heightfield.resolution_m}m)")

        # Cache for next time
        cache.store(heightfield)
        click.echo("Cached for future use")

    # Build mesh
    click.echo("Building 3D mesh...")
    builder = MeshBuilder(
        base_thickness_m=base_thickness, wall_height_m=wall_height
    )
    mesh = builder.build(heightfield, scale_z=scale_z)
    click.echo(
        f"Mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces, "
        f"watertight={mesh.is_watertight}"
    )

    # Export STL
    click.echo(f"Exporting to {output}...")
    mesh.export(output)
    click.echo(f"✓ Saved to {output}")
    click.echo(f"License: {heightfield.license}")


if __name__ == "__main__":
    main()
