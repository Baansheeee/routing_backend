"""Tests for route summary and lexicographic recommendation."""

from django.test import SimpleTestCase

from routing.services.risk import RiskLevel
from routing.services.summary import recommend, summarize_route


def _cp(mile, owned, level, drivers=None):
    return {
        "mile_marker": mile,
        "owned_miles": owned,
        "eta": "2026-06-01T18:00:00Z",
        "route_total_miles": 100.0,
        "route_duration_seconds": 7200,
        "risk": {
            "final_level": level,
            "level": level,
            "drivers": drivers or [],
        },
    }


def _route(rid, severe=0, high=0, moderate=0, low=100, no_travel=0, duration=7200, avg=None):
    # Build simple checkpoint list matching mile buckets
    cps = []
    mile = 0.0
    for level, miles in (
        (RiskLevel.NO_TRAVEL, no_travel),
        (RiskLevel.SEVERE, severe),
        (RiskLevel.HIGH, high),
        (RiskLevel.MODERATE, moderate),
        (RiskLevel.LOW, low),
    ):
        if miles <= 0:
            continue
        cps.append(_cp(mile, miles, level))
        mile += miles
    summary = summarize_route(cps)
    summary["duration_seconds"] = duration
    return {
        "id": rid,
        "label": rid.replace("-", " ").title(),
        "duration_seconds": duration,
        "summary": summary,
    }


class SummaryTests(SimpleTestCase):
    def test_miles_by_level(self):
        cps = [
            _cp(0, 25, RiskLevel.LOW),
            _cp(25, 50, RiskLevel.HIGH),
            _cp(75, 25, RiskLevel.SEVERE),
        ]
        summary = summarize_route(cps)
        self.assertAlmostEqual(summary["high_miles"], 50)
        self.assertAlmostEqual(summary["severe_miles"], 25)
        self.assertTrue(summary["max_risk"] >= RiskLevel.SEVERE)

    def test_prefer_fewer_severe(self):
        a = _route("route-1", severe=10, high=0, low=90)
        b = _route("route-2", severe=0, high=20, low=80)
        result = recommend([a, b])
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_prefer_fewer_high_when_severe_tied(self):
        a = _route("route-1", severe=0, high=30, low=70)
        b = _route("route-2", severe=0, high=10, low=90)
        result = recommend([a, b])
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_prefer_lower_avg_risk(self):
        a = _route("route-1", severe=0, high=0, moderate=80, low=20)
        b = _route("route-2", severe=0, high=0, moderate=10, low=90)
        result = recommend([a, b])
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_prefer_shorter_time_when_risk_tied(self):
        a = _route("route-1", severe=0, high=0, low=100, duration=9000)
        b = _route("route-2", severe=0, high=0, low=100, duration=7000)
        result = recommend([a, b])
        self.assertEqual(result["recommended_route_id"], "route-2")

    def test_all_no_travel_picks_fewest_no_travel_miles(self):
        a = _route("route-1", no_travel=40, low=60)
        b = _route("route-2", no_travel=10, low=90)
        result = recommend([a, b])
        self.assertEqual(result["recommended_route_id"], "route-2")
        self.assertTrue(result["warnings"])
