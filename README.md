![](banner.jpg)

# map-generator

Convert any Google Maps location into a 3D-printable STL file.

Paste in a Google Maps URL and get back a watertight STL file ready to send straight to your 3D printer. The tool handles everything from coordinate extraction through to a fully sealed, printable mesh with a solid base.

---

## Requirements

- Python 3.9 or higher
- pip

---

## Installation

```bash
pip install map-generator
```

Or for development:

```bash
git clone https://github.com/darrenoakey/map-generator.git
cd map-generator
pip install -e .
```

---

## Usage

### Generate an STL from a Google Maps URL

```bash
map-generator generate 'https://www.google.com/maps/place/...' -o output.stl
```

Or simply:

```bash
map-generator 'https://www.google.com/maps/place/...' -o output.stl
```

### Inspect a URL without fetching elevation

```bash
map-generator inspect-url 'https://www.google.com/maps/place/...'
```

### Options for generate

| Option | Description | Default |
|---|---|---|
| `-o` / `--output` | Output STL file path | `map.stl` |
| `--z-scale` | Vertical exaggeration factor (increase for more dramatic terrain) | `1.8` |
| `--base-mm` | Sealed base thickness in millimetres | `4.0` |
| `--print-mm` | Physical footprint side length in millimetres | `100.0` |
| `--no-cache` | Skip elevation cache and fetch fresh data | (off) |
| `--verify` | Print detailed mesh validation | (off) |
| `-v` / `--verbose` | Verbose output during generation | (off) |

---

## Examples

### Basic: Generate with default settings

```bash
map-generator 'https://www.google.com/maps/place/Mount+Everest/@27.9881206,86.9249751,14z'
```

### Exaggerate terrain for visual impact

```bash
map-generator 'https://www.google.com/maps/place/Grand+Canyon/@36.0998,-113.8857,12z' \
  --z-scale 3.0 \
  -o grand_canyon.stl
```

### Create a larger print

```bash
map-generator 'https://www.google.com/maps/place/Mount+Fuji/@35.3606,138.7274,13z' \
  --print-mm 150 \
  --base-mm 6 \
  -o fuji.stl
```

### Inspect a URL first

```bash
map-generator inspect-url 'https://www.google.com/maps/place/Warrawee/'
```

---

## Getting a Google Maps URL

1. Open [Google Maps](https://maps.google.com) in your browser
2. Navigate to the location you want
3. Right-click and select "Share" or copy from the address bar

The tool works best with URLs containing altitude information (the `@lat,lon,altitude m/` part). Altitude helps calculate the correct viewport size for the 3D model.

---

## Data Sources

**Primary**: Open-Meteo API (free, no key required)
- Global elevation data at ~90m resolution
- CC0 license

The tool automatically handles elevation queries and caches results locally in `~/.cache/map-generator/` for future use.

---

## Output

The generated `.stl` file contains:

- **Topographic surface**: Terrain matching the selected location
- **Sealed flat base**: Watertight bottom for stable printing
- **Perimeter walls**: Connect the terrain to the base

The mesh is validated as watertight and ready for 3D printing. Load directly into your slicer (PrusaSlicer, Cura, Bambu Studio, etc.) with no repairs needed.

---

## License

MIT License. Elevation data from Open-Meteo is provided under CC0 (public domain).