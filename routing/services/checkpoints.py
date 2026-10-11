"""Sample checkpoints along a route and compute ETAs / owned miles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

ALLOWED_INTERVALS = frozenset({10, 25, 50})
METERS_PER_MILE = 1609.344


class CheckpointError(Exception):
    """Raised when checkpoint construction fails."""


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _interpolate_point(
    geometry: list[list[float]],
    cum_dist_m: list[float],
    target_m: float,
) -> tuple[float, float]:
    """Interpolate [lon, lat] at a target cumulative distance in meters."""
    if target_m <= cum_dist_m[0]:
        lon, lat = geometry[0]
        return float(lat), float(lon)
    if target_m >= cum_dist_m[-1]:
        lon, lat = geometry[-1]
        return float(lat), float(lon)

    for i in range(1, len(cum_dist_m)):
        if cum_dist_m[i] >= target_m:
            prev_m = cum_dist_m[i - 1]
            next_m = cum_dist_m[i]
            span = next_m - prev_m
            t = 0.0 if span <= 0 else (target_m - prev_m) / span
            lon1, lat1 = geometry[min(i - 1, len(geometry) - 1)]
            lon2, lat2 = geometry[min(i, len(geometry) - 1)]
            # Prefer matching geometry vertex count to cumulative arrays
            if len(geometry) == len(cum_dist_m):
                lon1, lat1 = geometry[i - 1]
                lon2, lat2 = geometry[i]
            lon = lon1 + t * (lon2 - lon1)
            lat = lat1 + t * (lat2 - lat1)
            return float(lat), float(lon)

    lon, lat = geometry[-1]
    return float(lat), float(lon)


def _duration_at_distance(
    cum_dist_m: list[float],
    cum_dur_s: list[float],
    target_m: float,
    total_duration_s: float,
    total_distance_m: float,
) -> float:
    """Interpolate driving seconds to reach ``target_m``."""
    if not cum_dist_m or not cum_dur_s or len(cum_dist_m) != len(cum_dur_s):
        if total_distance_m <= 0:
            return 0.0
        return total_duration_s * (target_m / total_distance_m)

    if target_m <= cum_dist_m[0]:
        return cum_dur_s[0]
    if target_m >= cum_dist_m[-1]:
        return cum_dur_s[-1]

    for i in range(1, len(cum_dist_m)):
        if cum_dist_m[i] >= target_m:
            prev_m, next_m = cum_dist_m[i - 1], cum_dist_m[i]
            prev_t, next_t = cum_dur_s[i - 1], cum_dur_s[i]
            span = next_m - prev_m
            t = 0.0 if span <= 0 else (target_m - prev_m) / span
            return prev_t + t * (next_t - prev_t)

    return cum_dur_s[-1]


def _owned_miles(mile_markers: list[float], total_miles: float) -> list[float]:
    """Distance-weighted ownership: midpoint-to-midpoint; ends get half a segment."""
    n = len(mile_markers)
    if n == 0:
        return []
    if n == 1:
        return [total_miles]

    owned: list[float] = []
    for i in range(n):
        if i == 0:
            mid_next = (mile_markers[0] + mile_markers[1]) / 2.0
            owned.append(mid_next - mile_markers[0])
        elif i == n - 1:
            mid_prev = (mile_markers[i - 1] + mile_markers[i]) / 2.0
            owned.append(mile_markers[i] - mid_prev)
        else:
            mid_prev = (mile_markers[i - 1] + mile_markers[i]) / 2.0
            mid_next = (mile_markers[i] + mile_markers[i + 1]) / 2.0
            owned.append(mid_next - mid_prev)
    return owned


def build_checkpoints(
    route: dict[str, Any],
    interval_miles: int | float,
    departure_dt: datetime,
) -> list[dict[str, Any]]:
    """Build checkpoints every ``interval_miles`` along ``route``.

    Always includes mile 0 and the route end. ETAs are timezone-aware UTC
    datetimes (callers may serialize to ISO-8601).
    """
    interval = int(interval_miles)
    if interval not in ALLOWED_INTERVALS:
        raise CheckpointError(
            f"checkpoint interval must be one of {sorted(ALLOWED_INTERVALS)}"
        )

    geometry = route.get("geometry") or []
    if len(geometry) < 2:
        raise CheckpointError("Route geometry must have at least 2 points")

    total_miles = float(route["distance_miles"])
    total_duration_s = float(route["duration_seconds"])
    total_m = total_miles * METERS_PER_MILE

    cum_dist_m = list(route.get("cumulative_distance_m") or [])
    cum_dur_s = list(route.get("cumulative_duration_s") or [])

    # Align cumulative arrays with geometry when possible
    if len(cum_dist_m) != len(geometry):
        # Build distance along line by linear index fallback
        if not cum_dist_m:
            cum_dist_m = [
                total_m * i / (len(geometry) - 1) for i in range(len(geometry))
            ]
        if not cum_dur_s or len(cum_dur_s) != len(cum_dist_m):
            cum_dur_s = [
                total_duration_s * (d / total_m if total_m else 0.0) for d in cum_dist_m
            ]

    departure = _ensure_utc(departure_dt)

    markers: list[float] = [0.0]
    mile = float(interval)
    while mile < total_miles - 1e-6:
        markers.append(round(mile, 6))
        mile += interval
    if total_miles > 0 and abs(markers[-1] - total_miles) > 1e-6:
        markers.append(round(total_miles, 6))
    elif total_miles == 0:
        markers = [0.0]

    owned = _owned_miles(markers, total_miles)
    checkpoints: list[dict[str, Any]] = []

    for mile_marker, owned_mi in zip(markers, owned):
        target_m = mile_marker * METERS_PER_MILE
        lat, lon = _interpolate_point(geometry, cum_dist_m, target_m)
        elapsed_s = _duration_at_distance(
            cum_dist_m, cum_dur_s, target_m, total_duration_s, total_m
        )
        eta = departure + timedelta(seconds=elapsed_s)
        checkpoints.append(
            {
                "mile_marker": mile_marker,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "eta": eta,
                "owned_miles": owned_mi,
            }
        )

    return checkpoints
