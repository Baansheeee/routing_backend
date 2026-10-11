"""Open-Meteo weather fetch with batching, dedupe, cache, and parallel requests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests
from django.conf import settings
from django.core.cache import cache

MAX_BATCH = 50
MAX_WORKERS = 5
FORECAST_MAX_DAYS = 16


class WeatherError(Exception):
    """Raised when weather fetching fails."""


class WeatherWarning(Exception):
    """Non-fatal weather horizon issue (optional use by callers)."""


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _round_coord(value: float) -> float:
    return round(float(value), 2)


def _cache_key(lat: float, lon: float, day: str) -> str:
    return f"weather:{lat:.2f}:{lon:.2f}:{day}"


def _base_url() -> str:
    return getattr(
        settings,
        "OPEN_METEO_BASE_URL",
        "https://api.open-meteo.com/v1/forecast",
    )


def _cache_ttl() -> int:
    return int(getattr(settings, "WEATHER_CACHE_SECONDS", 1800))


def _nearest_hour(dt: datetime) -> datetime:
    dt = _ensure_utc(dt)
    if dt.minute >= 30:
        dt = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        dt = dt.replace(minute=0, second=0, microsecond=0)
    return dt


def _validate_eta(eta: datetime, now: datetime | None = None) -> str | None:
    """Return a warning message if ETA is outside the usable forecast window."""
    now = _ensure_utc(now or datetime.now(timezone.utc))
    eta = _ensure_utc(eta)
    if eta < now - timedelta(hours=1):
        return "ETA is in the past relative to current time"
    horizon = now + timedelta(days=FORECAST_MAX_DAYS)
    if eta > horizon:
        return f"ETA is beyond the {FORECAST_MAX_DAYS}-day forecast horizon"
    return None


def _parse_open_meteo_payload(
    payload: dict[str, Any] | list[dict[str, Any]],
    rounded_points: list[tuple[float, float]],
) -> dict[tuple[float, float], dict[str, Any]]:
    """Map rounded (lat, lon) -> hourly series dict."""
    items = payload if isinstance(payload, list) else [payload]
    result: dict[tuple[float, float], dict[str, Any]] = {}

    for item, (lat, lon) in zip(items, rounded_points):
        hourly = item.get("hourly") or {}
        times = hourly.get("time") or []
        winds = hourly.get("wind_speed_10m") or []
        rains = hourly.get("rain") or []
        snows = hourly.get("snowfall") or []
        series = {
            "times": times,
            "wind_mph": winds,
            "rain_in_hr": rains,
            "snow_in_hr": snows,
        }
        result[(lat, lon)] = series

        # Cache by calendar day(s) present in the series
        days = sorted({t[:10] for t in times if t})
        for day in days:
            cache.set(_cache_key(lat, lon, day), series, _cache_ttl())

    return result


def _fetch_batch(
    points: list[tuple[float, float]],
    forecast_days: int,
) -> dict[tuple[float, float], dict[str, Any]]:
    if not points:
        return {}

    lats = ",".join(f"{lat:.2f}" for lat, _ in points)
    lons = ",".join(f"{lon:.2f}" for _, lon in points)
    params = {
        "latitude": lats,
        "longitude": lons,
        "hourly": "wind_speed_10m,rain,snowfall",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": "UTC",
        "forecast_days": min(max(forecast_days, 1), FORECAST_MAX_DAYS),
    }

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = requests.get(_base_url(), params=params, timeout=15)
            response.raise_for_status()
            return _parse_open_meteo_payload(response.json(), points)
        except requests.RequestException as exc:
            last_error = exc

    raise WeatherError(f"Open-Meteo request failed: {last_error}")


def _pick_hour(
    series: dict[str, Any],
    eta: datetime,
) -> dict[str, Any]:
    eta_hour = _nearest_hour(eta)
    target = eta_hour.strftime("%Y-%m-%dT%H:00")
    times: list[str] = series.get("times") or []

    if target in times:
        idx = times.index(target)
    elif times:
        # Closest available hour
        idx = min(
            range(len(times)),
            key=lambda i: abs(
                (
                    datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc)
                    - eta_hour
                ).total_seconds()
            ),
        )
    else:
        raise WeatherError("Open-Meteo returned no hourly times")

    def _val(key: str) -> float:
        values = series.get(key) or []
        if idx >= len(values) or values[idx] is None:
            return 0.0
        return float(values[idx])

    return {
        "wind_mph": _val("wind_mph"),
        "rain_in_hr": _val("rain_in_hr"),
        "snow_in_hr": _val("snow_in_hr"),
        "forecast_time": times[idx] if times else target,
    }


def fetch_weather_for_points(
    points: Iterable[tuple[float, float]],
    needed_hours: Iterable[datetime],
) -> list[dict[str, Any]]:
    """Fetch weather for each point at the hour of its ETA.

    ``points`` and ``needed_hours`` are parallel sequences.
    Returns one dict per input point: wind_mph, rain_in_hr, snow_in_hr,
    forecast_time, and optional ``warning``.
    """
    point_list = list(points)
    hour_list = list(needed_hours)
    if len(point_list) != len(hour_list):
        raise WeatherError("points and needed_hours must be the same length")

    now = datetime.now(timezone.utc)
    rounded = [(_round_coord(lat), _round_coord(lon)) for lat, lon in point_list]

    # Determine how many forecast days we need
    max_eta = max((_ensure_utc(h) for h in hour_list), default=now)
    days_needed = max(1, min(FORECAST_MAX_DAYS, (max_eta.date() - now.date()).days + 2))

    # Resolve from cache where possible; collect misses
    unique_needed: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    series_by_point: dict[tuple[float, float], dict[str, Any]] = {}

    for lat, lon in rounded:
        key_point = (lat, lon)
        if key_point in seen:
            continue
        seen.add(key_point)
        # Try cache for the earliest relevant day; if any day hits, reuse series
        day = _ensure_utc(hour_list[0]).strftime("%Y-%m-%d")
        cached = cache.get(_cache_key(lat, lon, day))
        if cached:
            series_by_point[key_point] = cached
        else:
            unique_needed.append(key_point)

    # Fetch misses in parallel batches
    batches = [
        unique_needed[i : i + MAX_BATCH] for i in range(0, len(unique_needed), MAX_BATCH)
    ]
    if batches:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
            futures = {
                pool.submit(_fetch_batch, batch, days_needed): batch for batch in batches
            }
            for future in as_completed(futures):
                series_by_point.update(future.result())

    results: list[dict[str, Any]] = []
    for (lat, lon), eta in zip(rounded, hour_list):
        warning = _validate_eta(eta, now=now)
        series = series_by_point.get((lat, lon))
        if not series:
            raise WeatherError(f"No weather data for point ({lat}, {lon})")
        picked = _pick_hour(series, eta)
        if warning:
            picked["warning"] = warning
        results.append(picked)

    return results


def fetch_hourly_series_for_points(
    points: Iterable[tuple[float, float]],
    start_hour: datetime,
    hours: int = 49,
) -> dict[tuple[float, float], list[dict[str, float]]]:
    """Fetch a contiguous hourly series for heatmap points.

    Returns mapping rounded (lat, lon) -> list of hour dicts with wind/rain/snow.
    """
    start = _nearest_hour(start_hour)
    point_list = [(_round_coord(lat), _round_coord(lon)) for lat, lon in points]
    unique: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for p in point_list:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    days_needed = max(1, min(FORECAST_MAX_DAYS, (hours // 24) + 2))
    series_by_point: dict[tuple[float, float], dict[str, Any]] = {}

    still_needed: list[tuple[float, float]] = []
    day = start.strftime("%Y-%m-%d")
    for lat, lon in unique:
        cached = cache.get(_cache_key(lat, lon, day))
        if cached:
            series_by_point[(lat, lon)] = cached
        else:
            still_needed.append((lat, lon))

    batches = [
        still_needed[i : i + MAX_BATCH] for i in range(0, len(still_needed), MAX_BATCH)
    ]
    if batches:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(batches))) as pool:
            futures = [
                pool.submit(_fetch_batch, batch, days_needed) for batch in batches
            ]
            for future in as_completed(futures):
                series_by_point.update(future.result())

    end = start + timedelta(hours=hours - 1)
    out: dict[tuple[float, float], list[dict[str, float]]] = {}
    for lat, lon in unique:
        series = series_by_point.get((lat, lon))
        if not series:
            raise WeatherError(f"No weather data for point ({lat}, {lon})")
        hour_rows: list[dict[str, float]] = []
        cursor = start
        while cursor <= end:
            picked = _pick_hour(series, cursor)
            hour_rows.append(
                {
                    "wind_mph": picked["wind_mph"],
                    "rain_in_hr": picked["rain_in_hr"],
                    "snow_in_hr": picked["snow_in_hr"],
                }
            )
            cursor += timedelta(hours=1)
        out[(lat, lon)] = hour_rows
    return out
