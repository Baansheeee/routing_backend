"""Route risk summaries and lexicographic recommendation."""

from __future__ import annotations

from typing import Any

from routing.services.risk import RiskLevel


def summarize_route(checkpoints_with_risk: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a route from checkpoints that already include risk + weather.

    Each checkpoint must provide: mile_marker, owned_miles, eta, risk.final_level
    (or risk.level), and optionally risk.drivers. Route totals may also be passed
    via optional keys on the first checkpoint's ``_route`` meta — callers should
    attach ``total_miles`` / ``duration_seconds`` via the wrapper in views, or
    pass them by enriching checkpoints. This function derives miles from owned
    miles and uses the last ETA as arrival.
    """
    if not checkpoints_with_risk:
        return {
            "total_miles": 0.0,
            "duration_seconds": 0.0,
            "arrival_eta": None,
            "miles_by_level": {level.name: 0.0 for level in RiskLevel},
            "severe_miles": 0.0,
            "high_miles": 0.0,
            "avg_risk": 0.0,
            "max_risk": RiskLevel.LOW.value,
            "has_no_travel": False,
            "worst_checkpoint": None,
        }

    miles_by_level = {level.name: 0.0 for level in RiskLevel}
    weighted_risk = 0.0
    total_owned = 0.0
    max_risk = RiskLevel.LOW
    worst: dict[str, Any] | None = None

    for cp in checkpoints_with_risk:
        risk = cp.get("risk") or {}
        level_val = risk.get("final_level", risk.get("level", RiskLevel.LOW))
        level = RiskLevel(int(level_val))
        owned = float(cp.get("owned_miles") or 0.0)
        miles_by_level[level.name] += owned
        weighted_risk += level.value * owned
        total_owned += owned
        if level > max_risk:
            max_risk = level
            worst = {
                "mile": cp.get("mile_marker"),
                "drivers": list(risk.get("drivers") or []),
            }

    total_miles = float(
        checkpoints_with_risk[0].get("route_total_miles")
        or checkpoints_with_risk[-1].get("mile_marker")
        or total_owned
    )
    duration_seconds = float(
        checkpoints_with_risk[0].get("route_duration_seconds") or 0.0
    )
    arrival = checkpoints_with_risk[-1].get("eta")
    if hasattr(arrival, "isoformat"):
        arrival_eta = arrival.isoformat().replace("+00:00", "Z")
    else:
        arrival_eta = arrival

    avg_risk = (weighted_risk / total_owned) if total_owned > 0 else 0.0

    return {
        "total_miles": round(total_miles, 3),
        "duration_seconds": duration_seconds,
        "arrival_eta": arrival_eta,
        "miles_by_level": {k: round(v, 3) for k, v in miles_by_level.items()},
        "severe_miles": round(miles_by_level[RiskLevel.SEVERE.name], 3),
        "high_miles": round(miles_by_level[RiskLevel.HIGH.name], 3),
        "avg_risk": round(avg_risk, 4),
        "max_risk": max_risk.value,
        "has_no_travel": miles_by_level[RiskLevel.NO_TRAVEL.name] > 0,
        "worst_checkpoint": worst,
        "no_travel_miles": round(miles_by_level[RiskLevel.NO_TRAVEL.name], 3),
    }


def _sort_key(summary: dict[str, Any], duration_seconds: float) -> tuple:
    """Lexicographic recommendation key (lower is better)."""
    no_travel_miles = float(summary.get("no_travel_miles") or 0.0)
    has_no_travel = bool(summary.get("has_no_travel"))
    # Prefer routes without NO_TRAVEL; among NO_TRAVEL routes, fewer such miles.
    return (
        1 if has_no_travel else 0,
        no_travel_miles,
        float(summary.get("severe_miles") or 0.0),
        float(summary.get("high_miles") or 0.0),
        float(summary.get("avg_risk") or 0.0),
        float(duration_seconds),
    )


def recommend(routes: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best route using the assignment's lexicographic order.

    Each route dict needs: id, label, duration_seconds, summary.
    """
    if not routes:
        return {
            "recommended_route_id": None,
            "reason": "No routes available",
            "warnings": ["No routes to recommend"],
        }

    ranked = sorted(
        routes,
        key=lambda r: _sort_key(r["summary"], r.get("duration_seconds") or 0.0),
    )
    best = ranked[0]
    best_sum = best["summary"]
    warnings: list[str] = []

    all_no_travel = all(r["summary"].get("has_no_travel") for r in routes)
    any_safe = any(not r["summary"].get("has_no_travel") for r in routes)

    if all_no_travel:
        warnings.append(
            "All routes contain No Travel segments; recommending the one with "
            "the fewest No Travel miles."
        )

    # Build a one-line reason
    reason_parts = [
        f"{best.get('label') or best['id']}: "
        f"{best_sum.get('severe_miles', 0):g} severe miles"
    ]

    if len(ranked) > 1:
        runner = ranked[1]
        rs = runner["summary"]
        high_delta = rs.get("high_miles", 0) - best_sum.get("high_miles", 0)
        severe_delta = rs.get("severe_miles", 0) - best_sum.get("severe_miles", 0)
        if all_no_travel:
            nt_delta = rs.get("no_travel_miles", 0) - best_sum.get("no_travel_miles", 0)
            reason_parts.append(
                f"{nt_delta:g} fewer no-travel miles than {runner.get('label') or runner['id']}"
            )
        elif severe_delta > 0.01:
            reason_parts.append(
                f"{severe_delta:g} fewer severe miles than {runner.get('label') or runner['id']}"
            )
        elif high_delta > 0.01:
            reason_parts.append(
                f"{high_delta:g} fewer high miles than {runner.get('label') or runner['id']}"
            )
        elif abs(rs.get("avg_risk", 0) - best_sum.get("avg_risk", 0)) > 1e-6:
            reason_parts.append("lowest average risk")
        else:
            reason_parts.append("shortest travel time among tied risk profiles")

    if any_safe and best_sum.get("has_no_travel"):
        # Should not happen given sort key, but keep defensive warning
        warnings.append("Recommended route still contains No Travel segments")

    return {
        "recommended_route_id": best["id"],
        "reason": ", ".join(reason_parts) + ".",
        "warnings": warnings,
    }
