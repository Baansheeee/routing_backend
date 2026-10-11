"""Corridor weather-risk heatmap for a 0–48 hour forecast scrubber."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

from routing.services.risk import assess_checkpoint
from routing.services.weather import fetch_hourly_series_for_points

METERS_PER_MILE = 1609.344
EARTH_RADIUS_MI = 3958.8
MAX_POINTS = 250
SAMPLE_EVERY_MILES = 20.0
OFFSET_MILES = 15.0


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _destination_point(
    lat: float, lon: float, distance_mi: float, bearing_deg: float
) -> tuple[float, float]:
    """Move from lat/lon by distance along a bearing (degrees)."""
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    ang = distance_mi / EARTH_RADIUS_MI
    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang)
        + math.cos(lat1) * math.sin(ang) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(
        dlon
    )
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def _sample_along_route(route: dict[str, Any], every_miles: float) -> list[tuple[float, float]]:
    geometry = route.get("geometry") or []
    if len(geometry) < 2:
        return []

    cum = route.get("cumulative_distance_m") or []
    total_m = float(route["distance_miles"]) * METERS_PER_MILE
    if len(cum) != len(geometry):
        cum = [total_m * i / (len(geometry) - 1) for i in range(len(geometry))]

    targets = [0.0]
    m = every_miles
    total_miles = float(route["distance_miles"])
    while m < total_miles:
        targets.append(m)
        m += every_miles
    targets.append(total_miles)

    points: list[tuple[float, float]] = []
    for mile in targets:
        target_m = mile * METERS_PER_MILE
        # Find segment
        lat = geometry[-1][1]
        lon = geometry[-1][0]
        for i in range(1, len(cum)):
            if cum[i] >= target_m:
                prev_m, next_m = cum[i - 1], cum[i]
                span = next_m - prev_m
                t = 0.0 if span <= 0 else (target_m - prev_m) / span
                lon1, lat1 = geometry[i - 1]
                lon2, lat2 = geometry[i]
                lon = lon1 + t * (lon2 - lon1)
                lat = lat1 + t * (lat2 - lat1)
                break
        points.append((lat, lon))
    return points


def _corridor_points(routes: Iterable[dict[str, Any]]) -> list[tuple[float, float]]:
    raw: list[tuple[float, float]] = []
    for route in routes:
        along = _sample_along_route(route, SAMPLE_EVERY_MILES)
        raw.extend(along)
        # Perpendicular offsets using local bearing between consecutive samples
        for i in range(len(along)):
            lat, lon = along[i]
            if i < len(along) - 1:
                br = _bearing(lat, lon, along[i + 1][0], along[i + 1][1])
            elif i > 0:
                br = _bearing(along[i - 1][0], along[i - 1][1], lat, lon)
            else:
                br = 0.0
            left = (br - 90.0) % 360.0
            right = (br + 90.0) % 360.0
            raw.append(_destination_point(lat, lon, OFFSET_MILES, left))
            raw.append(_destination_point(lat, lon, OFFSET_MILES, right))

    # Dedupe to 3-decimal degrees, cap at MAX_POINTS
    deduped: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for lat, lon in raw:
        key = (round(lat, 3), round(lon, 3))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
        if len(deduped) >= MAX_POINTS:
            break
    return deduped


def build_heatmap(
    routes: list[dict[str, Any]],
    departure_dt: datetime,
    load_lb: float,
    hours: range | None = None,
) -> dict[str, Any]:
    """Build a compact corridor heatmap for hours 0..48 from departure."""
    hour_range = hours if hours is not None else range(0, 49)
    hour_count = len(list(hour_range))
    start = _ensure_utc(departure_dt).replace(minute=0, second=0, microsecond=0)

    points = _corridor_points(routes)
    if not points:
        return {
            "start_time": start.isoformat().replace("+00:00", "Z"),
            "hours": hour_count,
            "points": [],
        }

    series = fetch_hourly_series_for_points(points, start, hours=hour_count)

    payload_points: list[dict[str, Any]] = []
    for lat, lon in points:
        key = (round(lat, 2), round(lon, 2))
        # series keys are 2-decimal rounded
        rows = series.get(key)
        if rows is None:
            # try exact from fetch rounding
            rows = series.get((round(lat, 2), round(lon, 2)))
        if not rows:
            continue
        risks: list[int] = []
        for row in rows[:hour_count]:
            assessment = assess_checkpoint(
                row["wind_mph"],
                row["rain_in_hr"],
                row["snow_in_hr"],
                load_lb,
            )
            risks.append(int(assessment["final_level"]))
        # Pad if short
        while len(risks) < hour_count:
            risks.append(risks[-1] if risks else 1)
        payload_points.append(
            {
                "lat": round(lat, 3),
                "lon": round(lon, 3),
                "risk": risks,
            }
        )

    return {
        "start_time": start.isoformat().replace("+00:00", "Z"),
        "hours": hour_count,
        "points": payload_points,
    }
