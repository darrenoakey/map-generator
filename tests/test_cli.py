"""End-to-end CLI tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# The project ships an installed console-script entry point
# ([project.scripts] map-generator = "map_generator.cli:main"), which is the
# intended invocation. `python -m map_generator.cli` does NOT run main() —
# the module has no `if __name__ == "__main__"` guard by design, since
# entry-points are the canonical path — so tests must call the real script.
MAP_GENERATOR_BIN = str(Path(sys.executable).with_name("map-generator"))

WARRAWEE_URL = (
    "https://www.google.com/maps/place/32+Mitchell+Cres,+Warrawee+NSW+2074/"
    "@-33.7368286,151.1084364,2934m/data=!3m1!1e3!4m6!3m5!"
    "1s0x6b12a7b427582d43:0x3b48700295d0b6eb!8m2!"
    "3d-33.7368471!4d151.1131143!16s%2Fg%2F11cpd8m8vp!5m1!1e3"
    "?entry=ttu&g_ep=EgoyMDI2MDYyNC4wIKXMDSoASAFQAw%3D%3D"
)


@pytest.mark.network
def test_generate_warrawee_house_includes_real_buildings(tmp_path):
    """End-to-end proof of the centering fix + buildings feature together.

    A tight --radius-m around the place-pin address (not the wide camera
    viewport) must produce an STL with real extruded buildings near the
    house — this is the exact scenario that was previously broken (wrong
    center, terrain-only output).
    """
    out = tmp_path / "house.stl"
    result = subprocess.run(
        [
            MAP_GENERATOR_BIN, "generate", WARRAWEE_URL,
            "-o", str(out), "--radius-m", "200", "--no-cache", "--verbose",
        ],
        capture_output=True, text=True, timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert out.exists()

    sidecar = json.loads(out.with_suffix(".json").read_text())
    assert sidecar["center_lat"] == pytest.approx(-33.7368471, abs=0.0001)
    assert sidecar["center_lon"] == pytest.approx(151.1131143, abs=0.0001)
    assert sidecar["buildings"] is not None
    assert sidecar["buildings"]["placed"] > 0
