"""DRF serializers for routing API input validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rest_framework import serializers

ALLOWED_INTERVALS = (10, 25, 50)
FORECAST_MAX_DAYS = 16


class LatLonSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    name = serializers.CharField(required=False, allow_blank=True, default="")


class PlaceField(serializers.Field):
    """Accept a place string or ``{lat, lon, name}`` object."""

    def to_internal_value(self, data):
        if isinstance(data, str):
            text = data.strip()
            if not text:
                raise serializers.ValidationError("Place must not be empty.")
            return {"query": text}
        if isinstance(data, dict):
            ser = LatLonSerializer(data=data)
            ser.is_valid(raise_exception=True)
            return {
                "lat": ser.validated_data["lat"],
                "lon": ser.validated_data["lon"],
                "name": ser.validated_data.get("name") or "",
            }
        raise serializers.ValidationError(
            "Place must be a string or an object with lat/lon."
        )


class AnalyzeSerializer(serializers.Serializer):
    origin = PlaceField()
    destination = PlaceField()
    departure_time = serializers.DateTimeField()
    load_weight_lb = serializers.FloatField()
    checkpoint_interval_miles = serializers.IntegerField(required=False, default=25)

    def validate_load_weight_lb(self, value: float) -> float:
        if value <= 0:
            raise serializers.ValidationError("load_weight_lb must be greater than 0.")
        return value

    def validate_checkpoint_interval_miles(self, value: int) -> int:
        if value not in ALLOWED_INTERVALS:
            raise serializers.ValidationError(
                f"checkpoint_interval_miles must be one of {list(ALLOWED_INTERVALS)}."
            )
        return value

    def validate_departure_time(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if value < now - timedelta(hours=1):
            raise serializers.ValidationError(
                "departure_time is too far in the past for a usable forecast."
            )
        if value > now + timedelta(days=FORECAST_MAX_DAYS):
            raise serializers.ValidationError(
                f"departure_time must be within {FORECAST_MAX_DAYS} days."
            )
        return value

    def validate(self, attrs):
        origin = attrs["origin"]
        destination = attrs["destination"]

        def _key(place: dict) -> tuple:
            if "lat" in place and "lon" in place:
                return (round(place["lat"], 5), round(place["lon"], 5))
            return ("q", place.get("query", "").strip().lower())

        if _key(origin) == _key(destination):
            raise serializers.ValidationError(
                {"destination": "origin and destination must be different."}
            )
        return attrs


class HeatmapSerializer(AnalyzeSerializer):
    """Same body as analyze; interval is unused but accepted for symmetry."""
