"""Tests for URL parsing."""

import pytest

from map_generator.url_parser import parse_google_maps_url

WARRAWEE_URL = (
    "https://www.google.com/maps/place/32+Mitchell+Cres,+Warrawee+NSW+2074/"
    "@-33.7368286,151.1084364,2934m/data=!3m1!1e3!4m6!3m5!"
    "1s0x6b12a7b427582d43:0x3b48700295d0b6eb!8m2!"
    "3d-33.7368471!4d151.1131143!16s%2Fg%2F11cpd8m8vp!5m1!1e3"
    "?entry=ttu&g_ep=EgoyMDI2MDYyNC4wIKXMDSoASAFQAw%3D%3D"
)


def test_parse_warrawee_altitude_url():
    """Warrawee URL centers on the place pin, not the wide camera viewport.

    The URL carries two coordinate pairs: the camera viewport center
    (@-33.7368286,151.1084364) and the place-pin marker
    (!3d-33.7368471!4d151.1131143), ~430m apart. The pin is the real address
    — independently confirmed via Nominatim geocoding "32 Mitchell Crescent,
    Warrawee" to -33.7368010,151.1131290, which matches the pin, not the
    camera center — so it must win when both are present.
    """
    extent = parse_google_maps_url(WARRAWEE_URL)

    assert extent.center_lat == pytest.approx(-33.7368471, abs=0.0001)
    assert extent.center_lon == pytest.approx(151.1131143, abs=0.0001)
    assert extent.altitude_m == pytest.approx(2934, abs=1)
    assert extent.map_type == "3d"


def test_place_pin_preferred_over_camera_center():
    """A URL with a place-pin marker centers on the pin, not the camera."""
    url = (
        "https://www.google.com/maps/place/Some+Place/"
        "@10.0,20.0,500m/data=!3m1!1e3!4m6!3m5!"
        "1s0xdeadbeef:0xcafe!8m2!3d11.5!4d21.5!16s%2Fg%2Fxyz"
    )
    extent = parse_google_maps_url(url)
    assert extent.center_lat == pytest.approx(11.5, abs=1e-9)
    assert extent.center_lon == pytest.approx(21.5, abs=1e-9)
    # Altitude (ground-extent heuristic) still comes from the camera segment.
    assert extent.altitude_m == pytest.approx(500, abs=1)


def test_zoom_url_converts_to_altitude():
    """Zoom-level URLs are converted to an equivalent altitude."""
    url = "https://www.google.com/maps/@-33.7368,151.1084,15z/data=!3m1!1e3"
    extent = parse_google_maps_url(url)

    assert extent.center_lat == pytest.approx(-33.7368, abs=0.0001)
    assert extent.center_lon == pytest.approx(151.1084, abs=0.0001)
    assert 100 < extent.altitude_m < 50_000
    # zoom_level property round-trips near 15
    assert 13 < extent.zoom_level < 17


def test_bbox_is_square_centered():
    """Bounding box should be square and centred on given coordinates."""
    url = "https://www.google.com/maps/@0,0,10000m"
    extent = parse_google_maps_url(url)

    north, south, east, west = extent.bbox_degrees()

    assert north > 0
    assert south < 0
    assert east > 0
    assert west < 0
    # At equator lat/lon spans should be nearly equal
    assert abs((north - south) - (east - west)) < 0.01


def test_bbox_physical_size():
    """Ground extent should match altitude * 0.85."""
    altitude = 2934.0
    url = f"https://www.google.com/maps/@0,0,{altitude:.0f}m"
    extent = parse_google_maps_url(url)

    expected_ground_m = altitude * 0.85
    north, south, east, west = extent.bbox_degrees()
    actual_ground_m = (north - south) * 111_000.0

    assert actual_ground_m == pytest.approx(expected_ground_m, rel=0.01)


def test_invalid_url_raises():
    """Non-Maps URLs should raise ValueError."""
    with pytest.raises(ValueError):
        parse_google_maps_url("https://example.com")
