![](banner.jpg)

# map-generator

Convert any Google Maps URL into a 3D-printable STL model of the real terrain.

## Overview

**map-generator** takes a Google Maps URL and generates a watertight STL file of the terrain — and, by default, the real buildings on it — ready to send to your 3D printer. The tool fetches real elevation data (Google Maps Platform Elevation API when a billed key is configured — typically ~10 m resolution; otherwise OpenTopography Copernicus COP30 at 30 m/px, then Open-Meteo, then Open-Elevation as fully keyless fallbacks) and real building footprints (Microsoft's Global ML Building Footprints, falling back to OpenStreetMap), builds a printable mesh with a flat sealed base, and writes a hillshade preview PNG and a JSON sidecar alongside the STL.

Building footprints come from Microsoft/OpenStreetMap rather than Google: Google's own 3D building data (the Photorealistic 3D Tiles API) is a continuous draped photogrammetry mesh, not discrete tagged building objects, so there's no clean way to extract a single watertight, printable house solid from it without a much larger mesh-segmentation effort.

A "place" URL (e.g. a Google Maps search result) carries both a wide camera-viewport center and a precise place-pin marker for the actual address; the tool centers on the pin, so the output is genuinely centered on the address you searched for, not the wider map view.

## Installation

```bash
git clone https://github.com/darrenoakey/map-generator.git
cd map-generator
pip install -e .
```

### Optional: Google Maps Platform API key (best resolution, real Google data)

Requires a Google Cloud project with billing enabled and the Elevation API enabled (`gcloud services enable elevation-backend.googleapis.com`). Store the key in the macOS Keychain:

```bash
security add-generic-password -s map-generator-google-maps -w YOUR_KEY
```

This is Google's own elevation data, used under the [Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms) (not a CC/open license) — output using it must attribute "Powered by Google".

### Optional: OpenTopography API key (higher resolution, no Google account needed)

Store a free API key from [portal.opentopography.org](https://portal.opentopography.org/) in the macOS Keychain:

```bash
security add-generic-password -s map-generator-opentopography -w YOUR_KEY
```

Without either key the tool falls back through Open-Meteo then Open-Elevation automatically — both fully keyless.

## Usage

```
map-generator generate <URL> [OPTIONS]
map-generator <URL> [OPTIONS]          # shorthand — 'generate' is implicit
map-generator inspect-url <URL>        # dry-run: print coords/bbox without fetching
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `-o, --output` | `map.stl` | Output STL filename |
| `--source` | `auto` | Elevation source: `auto` \| `google` \| `opentopography` \| `open-meteo` \| `open-elevation` |
| `--radius-m` | from altitude | Ground-extent half-width in metres. Use a small value (150–300) to focus on one property and its immediate neighbours instead of a wide neighbourhood view |
| `--buildings` / `--no-buildings` | on | Extrude real building footprints onto the terrain |
| `--building-source` | `auto` | Building footprint source: `auto` \| `microsoft` \| `osm` |
| `--z-scale` | `1.8` | Vertical exaggeration |
| `--base-mm` | `4.0` | Sealed base thickness in mm |
| `--print-mm` | `100.0` | Physical footprint side length in mm |
| `--no-cache` | off | Skip elevation cache |
| `--verify` | off | Print watertight/volume/Euler validation |
| `-v, --verbose` | off | Verbose output |

## Examples

```bash
# Generate a model from a Google Maps URL (terrain + buildings, default radius from the URL's altitude)
map-generator 'https://www.google.com/maps/place/32+Mitchell+Cres,+Warrawee+NSW+2074/@-33.7368286,151.1084364,2934m/...' -o warrawee.stl

# Zoom to just one house and its neighbours
map-generator 'https://www.google.com/maps/place/.../...' -o house.stl --radius-m 200

# Terrain only, no buildings
map-generator 'https://maps.google.com/...' -o terrain_only.stl --no-buildings

# High z-scale for flat terrain
map-generator 'https://maps.google.com/...' -o flat_area.stl --z-scale 4.0

# Inspect URL without fetching elevation
map-generator inspect-url 'https://maps.google.com/...'
```

## Output Files

Each run produces three files alongside the STL:

| File | Description |
|------|-------------|
| `output.stl` | Watertight binary STL, flat sealed base, four walls, terrain surface |
| `output.json` | Sidecar: bbox, elevation source/license, grid dims, scale params |
| `output.png` | Hillshade preview of the elevation grid |

The mesh is guaranteed watertight (trimesh `is_watertight=True`), has consistent outward normals, and positive volume — validated before writing.

## Elevation Sources

| Source | Resolution | Key required |
|--------|-----------|--------------|
| Google Maps Platform Elevation API | ~10 m (varies by area) | Billed Google Cloud project |
| OpenTopography Copernicus COP30 | ~30 m | Free account at portal.opentopography.org |
| Open-Meteo | ~90 m | None |
| Open-Elevation (SRTM) | ~30 m | None |

`--source auto` tries Google (if configured), then OpenTopography, then Open-Meteo, then Open-Elevation. The two keyless sources are independent fallbacks of each other — Open-Meteo's free tier has a shared daily request quota that can run out under heavy use, so Open-Elevation keeps the tool working even then.

## Buildings

Real buildings are extruded as flat-roofed solids sitting flush on the terrain, scaled proportionally to the terrain's vertical exaggeration. Height comes from the footprint's real `height` (or estimated from `building:levels` for OSM); when no real height is available, a documented default (6 m, typical single-storey) is used and disclosed in the sidecar's `buildings.estimated_height_count` — never silently fabricated as measured data.

| Source | Coverage | Key required |
|--------|----------|---------------|
| Microsoft Global ML Building Footprints | Broad, ML-derived from satellite imagery | None |
| OpenStreetMap | Patchy outside well-mapped areas; used as fallback | None |

`--building-source auto` tries Microsoft first and falls back to OpenStreetMap if Microsoft has no footprints in the requested area. A very large extent (>50 km across) refuses to fetch buildings rather than silently downloading dozens of large tile files — pass `--radius-m` to focus the request, or `--no-buildings` to skip footprints for a wide terrain-only view.

## License

This project is licensed under [CC BY-NC 4.0](https://darren-static.waft.dev/license) - free to use and modify, but no commercial use without permission.

Elevation data: Google Maps Platform Elevation API (Google Maps Platform ToS — "Powered by Google" attribution required) when configured; otherwise Copernicus DEM GLO-30 (CC BY 4.0) via OpenTopography, Open-Meteo elevation (CC0), or Open-Elevation/SRTM (public domain).
Building footprints: Microsoft Global ML Building Footprints (ODbL); OpenStreetMap contributors (ODbL).
