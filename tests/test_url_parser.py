"""Tests for URL parsing."""

import pytest

from map_generator.url_parser import parse_google_maps_url


def test_parse_warrawee_3d_url():
    """Test parsing the 3D Google Maps URL for Warrawee, NSW."""
    url = "https://www.google.com/maps/place/32+Mitchell+Cres,+Warrawee+NSW+2074/@-33.7368286,151.1084364,2934m/data=!3m1!1e3!4m6!3m5!1s0x6b12a7b427582d43:0x3b48700295d0b6eb!8m2!3d-33.7368471!4d151.1131143!16s%2Fg%2F11cpd8m8vp!5m1!1e3?entry=ttu&g_ep=EgoyMDI2MDYyNC4wIKXMDSoASAFQAw%3D%3D"

    extent = parse_google_maps_url(url)

    # Check coordinates are extracted (2934m is altitude, converted to zoom level)
    assert extent.center_lat == pytest.approx(-33.7368286, abs=0.0001)
    assert extent.center_lon == pytest.approx(151.1084364, abs=0.0001)
    assert 10 < extent.zoom_level < 15  # Altitude 2934m → ~12.7 zoom
    assert extent.map_type == "3d"


def test_parse_simple_coordinate_url():
    """Test parsing a simple coordinate URL without place info."""
    url = "https://www.google.com/maps/@-33.7368,151.1084,15z/data=!3m1!1e3"

    extent = parse_google_maps_url(url)

    assert extent.center_lat == pytest.approx(-33.7368, abs=0.0001)
    assert extent.center_lon == pytest.approx(151.1084, abs=0.0001)
    assert extent.zoom_level == 15


def test_bbox_generation():
    """Test that bounding box is generated from extent."""
    extent = parse_google_maps_url(
        "https://www.google.com/maps/@0,0,15z/data=!3m1!1e3"
    )

    north, south, east, west = extent.bbox_meters()

    # Should be a square centered on origin
    assert north > 0
    assert south < 0
    assert east > 0
    assert west < 0
    assert abs((north - south) - (east - west)) < 0.01  # Square-ish


def test_invalid_url():
    """Test that invalid URLs raise errors."""
    with pytest.raises(ValueError):
        parse_google_maps_url("https://example.com")
