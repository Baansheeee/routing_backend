"""Mapbox Directions v5: fetch up to 3 distinct driving routes."""

from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    """Raised when route fetching fails."""


def _token() -> str:
    token = getattr(settings, "MAPBOX_TOKEN", "") or ""
    if not token:
        raise RoutingError("MAPBOX_TOKEN is not configured")
    return token


def _miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def _build_cumulative(
    legs: list[dict[str, Any]],
) -> tuple[list[float], list[float]]:
    """Build cumulative distance (meters) and duration (seconds) along the route.

    Mapbox annotations are per-segment between consecutive geometry vertices.
    """
    cum_dist = [0.0]
    cum_dur = [0.0]
    for leg in legs:
        annotation = leg.get("annotation") or {}
        distances = annotation.get("distance") or []
        durations = annotation.get("duration") or []
        for d, t in zip(distances, durations):
            cum_dist.append(cum_dist[-1] + float(d))
            cum_dur.append(cum_dur[-1] + float(t))
    return cum_dist, cum_dur


def _normalize_route(raw: dict[str, Any], index: int, label: str) -> dict[str, Any]:
    geometry = raw.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if not coords:
        raise RoutingError("Route geometry is empty")

    legs = raw.get("legs") or []
    cum_dist_m, cum_dur_s = _build_cumulative(legs)

    # If annotations missing, fall back to evenly spaced placeholders keyed by total.
    if len(cum_dist_m) < 2:
        total_m = float(raw.get("distance") or 0.0)
        total_s = float(raw.get("duration") or 0.0)
        n = len(coords)
        if n < 2:
            cum_dist_m = [0.0, total_m]
            cum_dur_s = [0.0, total_s]
        else:
            cum_dist_m = [total_m * i / (n - 1) for i in range(n)]
            cum_dur_s = [total_s * i / (n - 1) for i in range(n)]

    distance_m = float(raw.get("distance") or cum_dist_m[-1])
    duration_s = float(raw.get("duration") or cum_dur_s[-1])

    return {
        "id": f"route-{index}",
        "label": label,
        "distance_miles": round(_miles(distance_m), 3),
        "duration_seconds": round(duration_s, 1),
        "geometry": [[float(lon), float(lat)] for lon, lat in coords],
        "cumulative_distance_m": cum_dist_m,
        "cumulative_duration_s": cum_dur_s,
    }


def _sample_points(geometry: list[list[float]], count: int = 8) -> list[tuple[float, float]]:
    if not geometry:
        return []
    if len(geometry) <= count:
        return [(p[0], p[1]) for p in geometry]
    step = (len(geometry) - 1) / (count - 1)
    return [
        (geometry[int(round(i * step))][0], geometry[int(round(i * step))][1])
        for i in range(count)
    ]


def _routes_similar(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Treat routes as duplicates if distance/duration and sampled points are close."""
    if abs(a["distance_miles"] - b["distance_miles"]) > 2.0:
        return False
    if abs(a["duration_seconds"] - b["duration_seconds"]) > 180:
        return False

    sa = _sample_points(a["geometry"])
    sb = _sample_points(b["geometry"])
    if len(sa) != len(sb):
        return False

    # ~0.01 deg ≈ 0.7 mi; require most samples to be near each other
    close = 0
    for (lon1, lat1), (lon2, lat2) in zip(sa, sb):
        if abs(lon1 - lon2) < 0.05 and abs(lat1 - lat2) < 0.05:
            close += 1
    return close >= max(1, int(0.75 * len(sa)))


def _fetch_directions(
    origin: dict[str, float],
    destination: dict[str, float],
    *,
    profile: str = "driving",
    exclude: str | None = None,
) -> list[dict[str, Any]]:
    coords = f"{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}"
    url = f"https://api.mapbox.com/directions/v5/mapbox/{profile}/{coords}"
    params: dict[str, Any] = {
        "access_token": _token(),
        "alternatives": "true",
        "geometries": "geojson",
        "overview": "full",
        "annotations": "distance,duration",
        "steps": "false",
    }
    if exclude:
        params["exclude"] = exclude

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except requests.Timeout as exc:
        raise RoutingError("Mapbox Directions timed out") from exc
    except requests.RequestException as exc:
        raise RoutingError(f"Mapbox Directions failed: {exc}") from exc

    data = response.json()
    if data.get("code") and data["code"] != "Ok":
        raise RoutingError(f"Mapbox Directions error: {data.get('message') or data['code']}")
    return data.get("routes") or []


def get_routes(
    origin: dict[str, float],
    destination: dict[str, float],
) -> list[dict[str, Any]]:
    """Return up to 3 distinct routes between origin and destination.

    Origin/destination must include ``lat`` and ``lon``.
    """
    variants: list[tuple[str, str | None, str]] = [
        ("driving", None, "Primary"),
        ("driving", "toll", "Avoid tolls"),
        ("driving", "motorway", "Avoid motorways"),
        ("driving-traffic", None, "Traffic-aware"),
    ]

    collected: list[dict[str, Any]] = []
    labels_used = 0

    for profile, exclude, label_base in variants:
        if len(collected) >= 3:
            break
        try:
            raw_routes = _fetch_directions(
                origin, destination, profile=profile, exclude=exclude
            )
        except RoutingError:
            if not collected:
                raise
            continue

        for raw in raw_routes:
            try:
                labels_used += 1
                candidate = _normalize_route(
                    raw, index=len(collected) + 1, label=f"Route {labels_used}"
                )
                # Prefer descriptive label for non-primary variants when unique
                if exclude or profile != "driving":
                    candidate["label"] = label_base
            except RoutingError:
                continue

            if any(_routes_similar(candidate, existing) for existing in collected):
                continue

            collected.append(candidate)
            if len(collected) >= 3:
                break

    if not collected:
        raise RoutingError("No routes found between the given points")

    # Re-number ids/labels for a clean response
    for i, route in enumerate(collected, start=1):
        route["id"] = f"route-{i}"
        if not route["label"].startswith("Route"):
            route["label"] = f"Route {i} ({route['label']})"
        else:
            route["label"] = f"Route {i}"

    return collected
