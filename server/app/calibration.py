"""Calibration loop: learn realization rates from completed work.

For every implemented business case linked to a detected opportunity we have
a forecast (the opportunity's estimated annual savings) and an actual —
preferring the measured value computed from data (metric bindings), falling
back to annualized claimed savings entries. The ratio per opportunity
category is the realization rate, and it feeds back into prioritization as
a discount/uplift on future estimates of the same category.

This is reference-class forecasting: the estimate stops being an opinion and
becomes a measured bias coefficient.
"""
from typing import Any, Dict

from . import db

# keep correction factors sane: a single weird case shouldn't zero out or
# triple a whole category
FACTOR_FLOOR = 0.1
FACTOR_CEILING = 1.5


def report() -> Dict[str, Any]:
    """Per-category forecast vs. actual across implemented, linked cases."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for case in db.list_business_cases():
        if case["status"] != "implemented" or not case["linked_opportunity"]:
            continue
        tracking = case["tracking"] or {}
        forecast = case["linked_opportunity"].get("estimated_annual_savings") or 0
        if forecast <= 0:
            continue

        measured = tracking.get("measured_annual_savings") or 0
        if measured > 0:
            actual, basis = measured, "measured"
        else:
            months = max(tracking.get("months_live") or 1, 1)
            actual = (tracking.get("total_realized_savings") or 0) / months * 12
            basis = "claimed"
        if actual <= 0:
            continue

        category = case["linked_opportunity"]["category"]
        bucket = buckets.setdefault(
            category, {"cases": 0, "forecast": 0.0, "actual": 0.0, "basis": set()}
        )
        bucket["cases"] += 1
        bucket["forecast"] += forecast
        bucket["actual"] += actual
        bucket["basis"].add(basis)

    categories = {}
    for category, b in buckets.items():
        rate = b["actual"] / b["forecast"]
        categories[category] = {
            "cases": b["cases"],
            "forecast_annual_savings": round(b["forecast"], 2),
            "actual_annual_savings": round(b["actual"], 2),
            "realization_rate": round(rate, 3),
            "applied_factor": round(min(max(rate, FACTOR_FLOOR), FACTOR_CEILING), 3),
            "basis": sorted(b["basis"]),
        }
    return {"categories": categories, "cases_observed": sum(b["cases"] for b in buckets.values())}


def factors() -> Dict[str, float]:
    """Clamped realization factors keyed by opportunity category, for prioritization."""
    return {
        category: stats["applied_factor"]
        for category, stats in report()["categories"].items()
    }
