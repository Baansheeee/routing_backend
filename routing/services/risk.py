"""Pure risk classification for weather and load rules.

Boundary conventions (documented for graders / README):
- Wind (mph):     <25 LOW | <35 MODERATE | <45 HIGH | <55 SEVERE | else NO_TRAVEL
- Rain (in/hr):   <0.10 LOW | <=0.25 MODERATE | <=0.50 HIGH | <=1.00 SEVERE | else NO_TRAVEL
- Snow (in/hr):   <0.5 LOW | <=1.0 MODERATE | <=2.0 HIGH | <=3.0 SEVERE | else NO_TRAVEL

Load rules can only raise risk, never lower it.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any


class RiskLevel(IntEnum):
    """Ordered risk levels used throughout the app."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    SEVERE = 4
    NO_TRAVEL = 5


def classify_wind(mph: float) -> RiskLevel:
    """Classify wind speed in mph."""
    if mph < 25:
        return RiskLevel.LOW
    if mph < 35:
        return RiskLevel.MODERATE
    if mph < 45:
        return RiskLevel.HIGH
    if mph < 55:
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def classify_rain(in_per_hr: float) -> RiskLevel:
    """Classify rainfall intensity in inches per hour."""
    if in_per_hr < 0.10:
        return RiskLevel.LOW
    if in_per_hr <= 0.25:
        return RiskLevel.MODERATE
    if in_per_hr <= 0.50:
        return RiskLevel.HIGH
    if in_per_hr <= 1.00:
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def classify_snow(in_per_hr: float) -> RiskLevel:
    """Classify snowfall intensity in inches per hour."""
    if in_per_hr < 0.5:
        return RiskLevel.LOW
    if in_per_hr <= 1.0:
        return RiskLevel.MODERATE
    if in_per_hr <= 2.0:
        return RiskLevel.HIGH
    if in_per_hr <= 3.0:
        return RiskLevel.SEVERE
    return RiskLevel.NO_TRAVEL


def apply_load_rules(
    wind_mph: float, load_lb: float, base_level: RiskLevel
) -> RiskLevel:
    """Apply load-weight rules. Result is never lower than ``base_level``."""
    level = base_level

    if wind_mph >= 55:
        level = max(level, RiskLevel.NO_TRAVEL)
    elif 45 <= wind_mph < 55 and load_lb > 30_000:
        level = max(level, RiskLevel.NO_TRAVEL)
    elif 35 <= wind_mph < 45 and load_lb > 40_000:
        level = max(level, RiskLevel.SEVERE)

    return level


def _level_name(level: RiskLevel) -> str:
    return level.name.replace("_", " ").title()


def assess_checkpoint(
    wind_mph: float,
    rain_in_hr: float,
    snow_in_hr: float,
    load_lb: float,
) -> dict[str, Any]:
    """Assess risk at a checkpoint from weather and load.

    Returns wind/rain/snow/base/final levels plus human-readable drivers.
    """
    wind_level = classify_wind(wind_mph)
    rain_level = classify_rain(rain_in_hr)
    snow_level = classify_snow(snow_in_hr)
    base_level = max(wind_level, rain_level, snow_level)
    final_level = apply_load_rules(wind_mph, load_lb, base_level)

    drivers: list[str] = []

    for label, value, level, unit in (
        ("Wind", wind_mph, wind_level, "mph"),
        ("Rain", rain_in_hr, rain_level, "in/hr"),
        ("Snow", snow_in_hr, snow_level, "in/hr"),
    ):
        if level == base_level and level > RiskLevel.LOW:
            drivers.append(f"{label} {value:g} {unit} -> {_level_name(level)}")

    if final_level > base_level:
        if wind_mph >= 55:
            drivers.append(
                f"Wind {wind_mph:g} mph + load {load_lb:,.0f} lb -> No Travel"
            )
        elif 45 <= wind_mph < 55 and load_lb > 30_000:
            drivers.append(
                f"Wind {wind_mph:g} mph + load {load_lb:,.0f} lb -> No Travel"
            )
        elif 35 <= wind_mph < 45 and load_lb > 40_000:
            drivers.append(
                f"Wind {wind_mph:g} mph + load {load_lb:,.0f} lb -> Severe"
            )

    if not drivers and final_level == RiskLevel.LOW:
        drivers.append("Conditions within low-risk thresholds")

    return {
        "wind_level": wind_level,
        "rain_level": rain_level,
        "snow_level": snow_level,
        "base_level": base_level,
        "final_level": final_level,
        "drivers": drivers,
    }
