"""Mapbox Geocoding v5 helpers (temporary geocoding; results are not stored)."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings


class GeocodingError(Exception):
    """Raised when geocoding fails or returns no results."""


def _token() -> str:
    token = getattr(settings, "MAPBOX_TOKEN", "") or ""
    if not token:
        raise GeocodingError("MAPBOX_TOKEN is not configured")
    return token


def _feature_to_place(feature: dict[str, Any]) -> dict[str, Any]:
    lon, lat = feature["geometry"]["coordinates"]
    return {
        "name": feature.get("place_name") or feature.get("text") or "",
        "lat": float(lat),
        "lon": float(lon),
    }


def _geocode_request(query: str, limit: int) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        raise GeocodingError("Geocode query must not be empty")

    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(query)}.json"
    try:
        response = requests.get(
            url,
            params={
                "access_token": _token(),
                "limit": limit,
                "autocomplete": "true" if limit > 1 else "false",
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.Timeout as exc:
        raise GeocodingError("Mapbox geocoding timed out") from exc
    except requests.RequestException as exc:
        raise GeocodingError(f"Mapbox geocoding failed: {exc}") from exc

    data = response.json()
    features = data.get("features") or []
    return [_feature_to_place(f) for f in features]


def geocode(query: str) -> dict[str, Any]:
    """Resolve a place query to a single ``{name, lat, lon}`` result."""
    places = _geocode_request(query, limit=1)
    if not places:
        raise GeocodingError(f"No results found for '{query}'")
    return places[0]


def suggest(query: str) -> list[dict[str, Any]]:
    """Return up to 5 autocomplete candidates."""
    query = (query or "").strip()
    if not query:
        return []
    return _geocode_request(query, limit=5)
