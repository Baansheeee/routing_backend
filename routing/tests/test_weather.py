"""Tests for Open-Meteo weather batching, hour selection, and cache."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from routing.services.weather import WeatherError, fetch_weather_for_points


def _hourly_payload(lat=32.8, lon=-96.8):
    times = [
        "2026-06-01T11:00",
        "2026-06-01T12:00",
        "2026-06-01T13:00",
    ]
    return {
        "latitude": lat,
        "longitude": lon,
        "hourly": {
            "time": times,
            "wind_speed_10m": [10.0, 22.0, 40.0],
            "rain": [0.0, 0.12, 0.0],
            "snowfall": [0.0, 0.0, 0.0],
        },
    }


@override_settings(
    OPEN_METEO_BASE_URL="https://example.test/forecast",
    WEATHER_CACHE_SECONDS=1800,
)
class WeatherTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    @patch("routing.services.weather.requests.get")
    def test_hour_selection(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: _hourly_payload()
        )
        mock_get.return_value.raise_for_status = lambda: None
        eta = datetime(2026, 6, 1, 12, 20, tzinfo=timezone.utc)
        rows = fetch_weather_for_points([(32.8, -96.8)], [eta])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["wind_mph"], 22.0)
        self.assertEqual(rows[0]["rain_in_hr"], 0.12)
        self.assertEqual(rows[0]["forecast_time"], "2026-06-01T12:00")

    @patch("routing.services.weather.requests.get")
    def test_batching_chunks(self, mock_get):
        # 55 unique points -> 2 batches (50 + 5)
        points = [(30.0 + i * 0.01, -100.0 - i * 0.01) for i in range(55)]
        etas = [datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)] * 55

        def fake_get(url, params=None, timeout=15):
            lats = params["latitude"].split(",")
            payload = [_hourly_payload(float(lat), -96.8) for lat in lats]
            if len(payload) == 1:
                body = payload[0]
            else:
                body = payload
            resp = MagicMock(status_code=200, json=lambda: body)
            resp.raise_for_status = lambda: None
            return resp

        mock_get.side_effect = fake_get
        rows = fetch_weather_for_points(points, etas)
        self.assertEqual(len(rows), 55)
        self.assertEqual(mock_get.call_count, 2)

    @patch("routing.services.weather.requests.get")
    def test_cache_hit_skips_http(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200, json=lambda: _hourly_payload()
        )
        mock_get.return_value.raise_for_status = lambda: None
        eta = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        fetch_weather_for_points([(32.8, -96.8)], [eta])
        self.assertEqual(mock_get.call_count, 1)
        fetch_weather_for_points([(32.8, -96.8)], [eta])
        self.assertEqual(mock_get.call_count, 1)

    @patch("routing.services.weather.requests.get")
    def test_error_after_retry(self, mock_get):
        mock_get.side_effect = Exception("network down")
        # requests.RequestException path — simulate via side_effect type
        import requests

        mock_get.side_effect = requests.ConnectionError("down")
        with self.assertRaises(WeatherError):
            fetch_weather_for_points(
                [(32.8, -96.8)],
                [datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)],
            )
        self.assertEqual(mock_get.call_count, 2)
