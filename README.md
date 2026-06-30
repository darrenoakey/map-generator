![](banner.jpg)

# map-generator

Convert any Google Maps location into a 3D-printable STL file.

Paste in a Google Maps URL and get back a watertight STL file ready to send straight to your 3D printer. The tool handles everything from coordinate extraction through to a fully sealed, printable mesh with a solid base.

---

## Requirements

- Python 3.10 or higher

---

## Installation

```bash
pip install -e .
```

---

## Usage

```bash
map-generator '<google-maps-url>' -o output.stl
```

The Google Maps URL should be a link to a location — copy it directly from your browser's address bar or from the Share menu in Google Maps.

### Options

| Option | Description | Default |
|---|---|---|
| `--source` | Elevation data source (`opentopography` or `open-meteo`) | `opentopography` |
| `--scale-z` | Vertical exaggeration factor — increase to make terrain features more pronounced | `1.0` |
| `--base-thickness` | Thickness of the sealed base in millimetres | `3.0` |
| `--wall-height` | Height of the perimeter wall in millimetres | `2.0` |
| `-o` / `--output` | Output file path | `output.stl` |

---

## Examples

### Basic usage

Generate an STL from a Google Maps URL with default settings:

```bash
map-generator 'https://www.google.com/maps/place/Mount+Everest/@27.9881206,86.9249751,14z' -o everest.stl
```

### Exaggerate the terrain

Increase vertical scale to make subtle terrain features stand out more when printed:

```bash
map-generator 'https://www.google.com/maps/place/Grand+Canyon/@36.0998,-113.8857,12z' \
  --scale-z 2.5 \
  -o grand_canyon.stl
```

### Thicker base for large prints

Add a thicker base for a more stable print:

```bash
map-generator 'https://www.google.com/maps/place/Mount+Fuji/@35.3606,138.7274,13z' \
  --base-thickness 6 \
  --wall-height 4 \
  -o fuji.stl
```

### Use an alternative elevation source

Switch to Open-Meteo if you prefer or need a different data source:

```bash
map-generator 'https://www.google.com/maps/place/Scottish+Highlands/@57.1214,-4.7264,12z' \
  --source open-meteo \
  -o highlands.stl
```

---

## Getting a Google Maps URL

1. Open [Google Maps](https://maps.google.com) in your browser
2. Navigate to the location you want
3. Copy the URL from your browser's address bar

The longer the URL, the more coordinate information it contains — using **Share → Copy link** from the Google Maps menu will give you the most precise URL.

---

## Output

The generated `.stl` file is a watertight mesh ready for 3D printing. It includes:

- A topographic surface matching the terrain at the selected location
- A flat, sealed base
- Perimeter walls connecting the terrain to the base

Load the `.stl` directly into your slicer (e.g. PrusaSlicer, Cura, Bambu Studio) with no repairs needed.

---

## License

CC BY-NC-4.0 — includes elevation data from Copernicus DEM. For personal and non-commercial use.