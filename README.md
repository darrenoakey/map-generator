# map-generator

Convert Google Maps URLs to 3D-printable STL files.

Pass in a Google Maps URL showing a location with 3D terrain view, and get back a watertight STL ready for 3D printing. The tool extracts coordinates from the URL, fetches elevation data from open sources (Copernicus DEM or Open-Meteo), builds a topographic 3D mesh with a sealed base, and exports it as STL.

## Installation

```bash
pip install -e .
```

## Usage

```bash
map-generator 'https://www.google.com/maps/place/32+Mitchell+Cres,...' -o output.stl
```

## Options

- `--source`: Elevation source (opentopography or open-meteo)
- `--scale-z`: Vertical exaggeration factor
- `--base-thickness`: Sealed base thickness in mm
- `--wall-height`: Perimeter wall height in mm

## License

CC BY-NC-4.0 (Copernicus DEM)
