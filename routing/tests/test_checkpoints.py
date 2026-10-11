"""Unit tests for checkpoint sampling, owned miles, and ETAs."""

from datetime import datetime, timezone

from django.test import SimpleTestCase

from routing.services.checkpoints import CheckpointError, build_checkpoints


def _sample_route(miles=100.0, hours=2.0):
    meters = miles * 1609.344
    seconds = hours * 3600
    geometry = [[-96.8, 32.8], [-100.0, 35.0], [-104.99, 39.74]]
    return {
        "id": "route-1",
        "label": "Route 1",
        "distance_miles": miles,
        "duration_seconds": seconds,
        "geometry": geometry,
        "cumulative_distance_m": [0.0, meters / 2, meters],
        "cumulative_duration_s": [0.0, seconds / 2, seconds],
    }


class CheckpointTests(SimpleTestCase):
    def test_monotonic_start_end(self):
        departure = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        cps = build_checkpoints(_sample_route(100), 25, departure)
        miles = [c["mile_marker"] for c in cps]
        self.assertEqual(miles[0], 0.0)
        self.assertAlmostEqual(miles[-1], 100.0, places=3)
        self.assertEqual(miles, sorted(miles))

    def test_owned_miles_sum(self):
        departure = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        route = _sample_route(100)
        cps = build_checkpoints(route, 25, departure)
        self.assertAlmostEqual(sum(c["owned_miles"] for c in cps), 100.0, places=5)

    def test_etas_increasing(self):
        departure = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        cps = build_checkpoints(_sample_route(100), 25, departure)
        etas = [c["eta"] for c in cps]
        self.assertEqual(etas[0], departure)
        for a, b in zip(etas, etas[1:]):
            self.assertLessEqual(a, b)

    def test_invalid_interval(self):
        departure = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
        with self.assertRaises(CheckpointError):
            build_checkpoints(_sample_route(), 15, departure)
