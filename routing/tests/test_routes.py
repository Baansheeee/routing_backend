"""Tests for Mapbox geocoding and directions parsing (HTTP mocked)."""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from routing.services.geocoding import GeocodingError, geocode, suggest
from routing.services.routes import RoutingError, get_routes, _routes_similar


def _geojson_route(distance_m=160934.4, duration_s=7200, shift=0.0):
    """~100 mile route with annotations for 3 vertices."""
    coords = [
        [-96.8 + shift, 32.8],
        [-100.0 + shift, 35.0],
        [-104.99 + shift, 39.74],
    ]
    return {
        "distance": distance_m,
        "duration": duration_s,
        "geometry": {"coordinates": coords},
        "legs": [
            {
                "annotation": {
                    "distance": [distance_m / 2, distance_m / 2],
                    "duration": [duration_s / 2, duration_s / 2],
                }
            }
        ],
    }


@override_settings(MAPBOX_TOKEN="test-token")
class GeocodingTests(SimpleTestCase):
    @patch("routing.services.geocoding.requests.get")
    def test_geocode_ok(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "features": [
                    {
                        "place_name": "Dallas, Texas",
                        "geometry": {"coordinates": [-96.8, 32.8]},
                    }
                ]
            },
        )
        mock_get.return_value.raise_for_status = lambda: None
        place = geocode("Dallas, TX")
        self.assertEqual(place["name"], "Dallas, Texas")
        self.assertAlmostEqual(place["lat"], 32.8)
        self.assertAlmostEqual(place["lon"], -96.8)

    @patch("routing.services.geocoding.requests.get")
    def test_geocode_not_found(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"features": []})
        mock_get.return_value.raise_for_status = lambda: None
        with self.assertRaises(GeocodingError):
            geocode("zzz-unknown-place")

    @patch("routing.services.geocoding.requests.get")
    def test_suggest_limit(self, mock_get):
        features = [
            {
                "place_name": f"Place {i}",
                "geometry": {"coordinates": [-96.0 - i, 32.0]},
            }
            for i in range(5)
        ]
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: {"features": features}
        )
        mock_get.return_value.raise_for_status = lambda: None
        results = suggest("Dal")
        self.assertEqual(len(results), 5)


@override_settings(MAPBOX_TOKEN="test-token")
class RoutesTests(SimpleTestCase):
    @patch("routing.services.routes._fetch_directions")
    def test_parses_three_alternatives(self, mock_fetch):
        mock_fetch.return_value = [
            _geojson_route(shift=0.0),
            _geojson_route(distance_m=170000, shift=0.2),
            _geojson_route(distance_m=180000, shift=0.4),
        ]
        routes = get_routes({"lat": 32.8, "lon": -96.8}, {"lat": 39.7, "lon": -105.0})
        self.assertEqual(len(routes), 3)
        self.assertEqual(routes[0]["id"], "route-1")
        self.assertIn("geometry", routes[0])
        self.assertGreater(routes[0]["distance_miles"], 0)
        self.assertEqual(len(routes[0]["cumulative_distance_m"]), 3)

    @patch("routing.services.routes._fetch_directions")
    def test_fallback_and_dedupe(self, mock_fetch):
        primary = [_geojson_route(shift=0.0), _geojson_route(shift=0.001)]  # near-dupe
        alt = [_geojson_route(distance_m=200000, shift=1.0)]

        def side_effect(origin, destination, profile="driving", exclude=None):
            if exclude is None and profile == "driving":
                return primary
            if exclude == "toll":
                return alt
            return []

        mock_fetch.side_effect = side_effect
        routes = get_routes({"lat": 32.8, "lon": -96.8}, {"lat": 39.7, "lon": -105.0})
        self.assertEqual(len(routes), 2)
        self.assertFalse(_routes_similar(routes[0], routes[1]))

    @patch("routing.services.routes._fetch_directions")
    def test_no_routes_raises(self, mock_fetch):
        mock_fetch.return_value = []
        with self.assertRaises(RoutingError):
            get_routes({"lat": 0, "lon": 0}, {"lat": 1, "lon": 1})
