"""Metric bindings: KPI values computed from ingested data, not typed by people.

A metric definition is a small declarative query over one ingested dataset:

    {"metric": "sum" | "avg" | "count",
     "source": "cmdb" | "erp" | "cloud" | "itsm",
     "field": "monthly_cost",                  # required for sum/avg
     "filters": [{"field": "resource_id", "op": "in", "values": [...]},
                 {"field": "category",    "op": "eq", "value": "password reset"}]}

The same definition is evaluated at business-case creation (the frozen
baseline) and again at any later point (observations) — same query, same
source, two points in time. That removes the human from the number.
"""
from typing import Any, Dict, List, Optional

from .ingestion import SOURCE_TYPES

ALLOWED_METRICS = {"sum", "avg", "count"}
ALLOWED_OPS = {"eq", "neq", "in"}

# field -> unit, used to annualize deltas where the field is a money rate
UNIT_BY_FIELD = {
    "annual_cost": "usd_per_year",
    "monthly_cost": "usd_per_month",
    "amount": "usd",
}


class MetricError(ValueError):
    pass


def validate_definition(definition: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(definition, dict):
        raise MetricError("definition must be an object")
    metric = definition.get("metric")
    if metric not in ALLOWED_METRICS:
        raise MetricError(f"metric must be one of {sorted(ALLOWED_METRICS)}")
    source = definition.get("source")
    if source not in SOURCE_TYPES:
        raise MetricError(f"source must be one of {sorted(SOURCE_TYPES)}")
    if metric in ("sum", "avg") and not definition.get("field"):
        raise MetricError(f"'{metric}' requires a field")
    filters = definition.get("filters", [])
    if not isinstance(filters, list):
        raise MetricError("filters must be a list")
    for f in filters:
        if f.get("op") not in ALLOWED_OPS:
            raise MetricError(f"filter op must be one of {sorted(ALLOWED_OPS)}")
        if not f.get("field"):
            raise MetricError("each filter needs a field")
        if f["op"] == "in" and not isinstance(f.get("values"), list):
            raise MetricError("'in' filter needs a values list")
    return definition


def _norm(value: Any) -> str:
    return str("" if value is None else value).strip().lower()


def _matches(row: Dict[str, Any], filters: List[Dict[str, Any]]) -> bool:
    for f in filters:
        actual = _norm(row.get(f["field"]))
        if f["op"] == "eq":
            if actual != _norm(f.get("value")):
                return False
        elif f["op"] == "neq":
            if actual == _norm(f.get("value")):
                return False
        elif f["op"] == "in":
            if actual not in {_norm(v) for v in f.get("values", [])}:
                return False
    return True


def compute(definition: Dict[str, Any], datasets: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Evaluate a definition against the currently loaded datasets."""
    validate_definition(definition)
    rows = [
        r for r in datasets.get(definition["source"], [])
        if _matches(r, definition.get("filters", []))
    ]
    if definition["metric"] == "count":
        value: float = float(len(rows))
    else:
        numbers = [
            float(r[definition["field"]])
            for r in rows
            if isinstance(r.get(definition["field"]), (int, float))
        ]
        if definition["metric"] == "sum":
            value = sum(numbers)
        else:  # avg
            value = sum(numbers) / len(numbers) if numbers else 0.0
    return {"value": round(value, 2), "rows_matched": len(rows)}


def unit_for(definition: Dict[str, Any]) -> str:
    if definition["metric"] == "count":
        return "count"
    return UNIT_BY_FIELD.get(definition.get("field", ""), "value")


def annualized_delta(definition: Dict[str, Any], baseline: float, latest: float) -> Optional[float]:
    """Reduction vs. baseline expressed in $/yr, where the unit allows it.
    Positive = improvement (the metric went down)."""
    delta = baseline - latest
    unit = unit_for(definition)
    if unit == "usd_per_year":
        return round(delta, 2)
    if unit == "usd_per_month":
        return round(delta * 12, 2)
    return None
