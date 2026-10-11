"""Thin API views for weather-aware truck routing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from routing.serializers import AnalyzeSerializer, HeatmapSerializer
from routing.services.checkpoints import CheckpointError, build_checkpoints
from routing.services.geocoding import GeocodingError, geocode, suggest
from routing.services.heatmap import build_heatmap
from routing.services.risk import RiskLevel, assess_checkpoint
from routing.services.routes import RoutingError, get_routes
from routing.services.summary import recommend, summarize_route
from routing.services.weather import WeatherError, fetch_weather_for_points


def _resolve_place(place: dict[str, Any]) -> dict[str, Any]:
    if "lat" in place and "lon" in place:
        return {
            "name": place.get("name") or f"{place['lat']},{place['lon']}",
            "lat": float(place["lat"]),
            "lon": float(place["lon"]),
        }
    return geocode(place["query"])


def _eta_iso(eta: datetime) -> str:
    eta = eta if eta.tzinfo else eta.replace(tzinfo=timezone.utc)
    return eta.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _enrich_route(
    route: dict[str, Any],
    *,
    interval: int,
    departure: datetime,
    load_lb: float,
) -> dict[str, Any]:
    checkpoints = build_checkpoints(route, interval, departure)
    weather_rows = fetch_weather_for_points(
        [(cp["lat"], cp["lon"]) for cp in checkpoints],
        [cp["eta"] for cp in checkpoints],
    )

    enriched: list[dict[str, Any]] = []
    for cp, weather in zip(checkpoints, weather_rows):
        assessment = assess_checkpoint(
            weather["wind_mph"],
            weather["rain_in_hr"],
            weather["snow_in_hr"],
            load_lb,
        )
        final = assessment["final_level"]
        enriched.append(
            {
                "mile_marker": cp["mile_marker"],
                "lat": cp["lat"],
                "lon": cp["lon"],
                "eta": cp["eta"],
                "owned_miles": cp["owned_miles"],
                "route_total_miles": route["distance_miles"],
                "route_duration_seconds": route["duration_seconds"],
                "weather": {
                    "wind_mph": weather["wind_mph"],
                    "rain_in_hr": weather["rain_in_hr"],
                    "snow_in_hr": weather["snow_in_hr"],
                    "forecast_time": weather.get("forecast_time"),
                },
                "risk": {
                    "level": int(final),
                    "level_name": RiskLevel(final).name,
                    "drivers": assessment["drivers"],
                    "final_level": int(final),
                },
            }
        )

    summary = summarize_route(enriched)

    return {
        "id": route["id"],
        "label": route["label"],
        "geometry": route["geometry"],
        "distance_miles": route["distance_miles"],
        "duration_seconds": route["duration_seconds"],
        "summary": summary,
        "checkpoints": [
            {
                "mile": cp["mile_marker"],
                "lat": cp["lat"],
                "lon": cp["lon"],
                "eta": _eta_iso(cp["eta"]),
                "owned_miles": round(cp["owned_miles"], 3),
                "weather": {
                    "wind_mph": cp["weather"]["wind_mph"],
                    "rain_in_hr": cp["weather"]["rain_in_hr"],
                    "snow_in_hr": cp["weather"]["snow_in_hr"],
                },
                "risk": {
                    "level": cp["risk"]["level"],
                    "level_name": cp["risk"]["level_name"],
                    "drivers": cp["risk"]["drivers"],
                },
            }
            for cp in enriched
        ],
    }


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class GeocodeSuggestView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response(
                {"q": ["Query parameter 'q' is required."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            return Response({"results": suggest(q)})
        except GeocodingError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class AnalyzeView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        ser = AnalyzeSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        try:
            origin = _resolve_place(data["origin"])
            destination = _resolve_place(data["destination"])
            routes = get_routes(origin, destination)
            enriched_routes = [
                _enrich_route(
                    route,
                    interval=data["checkpoint_interval_miles"],
                    departure=data["departure_time"],
                    load_lb=data["load_weight_lb"],
                )
                for route in routes
            ]
            recommendation = recommend(enriched_routes)
        except (GeocodingError, RoutingError, WeatherError, CheckpointError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "origin": origin,
                "destination": destination,
                "routes": enriched_routes,
                "recommendation": recommendation,
            }
        )


class HeatmapView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        ser = HeatmapSerializer(data=request.data)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        try:
            origin = _resolve_place(data["origin"])
            destination = _resolve_place(data["destination"])
            routes = get_routes(origin, destination)
            heatmap = build_heatmap(
                routes,
                data["departure_time"],
                data["load_weight_lb"],
                hours=range(0, 49),
            )
        except (GeocodingError, RoutingError, WeatherError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(heatmap)
