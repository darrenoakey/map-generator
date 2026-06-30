![](banner.jpg)

# map-generator

Convert Google Maps URLs into 3D-printable STL models.

## Overview

**map-generator** takes a Google Maps URL for any location and generates a 3D-printable STL file of the terrain. Whether you want to print a topographic model of your hometown, a mountain range, or any geographic area visible on Google Maps, map-generator automates the entire process from URL to print-ready file.

## Installation

### Requirements

- Python 3.9 or higher

### Install from source

Clone the repository and install using pip:

```bash
git clone https://github.com/darreno/map-generator.git
cd map-generator
pip install -e .
```

To include mesh repair support:

```bash
pip install -e ".[repair]"
```

### Quick run (no manual install)

A convenience script is included that automatically sets up a virtual environment on first run:

```bash
./run [options]
```

## Usage

```
map-generator [OPTIONS] URL
```

### Arguments

| Argument | Description |
|----------|-------------|
| `URL` | A Google Maps URL pointing to the area you want to generate |

### Options

Run `map-generator --help` to see all available options.

## Examples

Generate a 3D model from a Google Maps URL:

```bash
map-generator "https://www.google.com/maps/@36.1069,-112.1129,12z"
```

Using the included run script:

```bash
./run "https://www.google.com/maps/@36.1069,-112.1129,12z"
```

Save the output to a specific file:

```bash
map-generator --output grand_canyon.stl "https://www.google.com/maps/@36.1069,-112.1129,12z"
```

## Output

The tool produces an `.stl` file that can be opened in any 3D printing slicer (such as PrusaSlicer, Cura, or Bambu Studio) and printed directly.

## License

This project is licensed under the MIT License.