"""Opportunity prioritization model.

Raw estimated savings is a bad ranking key on its own: it over-ranks large,
risky, expensive initiatives and buries fast cheap wins. This model scores
each opportunity 0-100 from three normalized components:

  value      — risk-adjusted annual savings (savings x detection confidence),
               log-scaled so one giant doesn't flatten the rest of the portfolio
  efficiency — payback ratio (risk-adjusted savings / estimated implementation
               cost), capped so trivial items can't dominate
  speed      — time-to-value implied by the effort rating
  simplicity — inverse of the opportunity's complexity rating (coordination
               burden and delivery risk: stakeholders, migrations, org change).
               Distinct from effort, which approximates labor/cost.

Weights are configurable per request so a customer can tilt toward quick wins
(efficiency/speed) or size-of-prize (value). Each opportunity also gets a
classic value-vs-effort quadrant label for portfolio conversations.

All cost/timing figures are planning heuristics for ranking — not quotes.
"""
import math
from statistics import median
from typing import Any, Dict, List, Optional

DEFAULT_WEIGHTS = {"value": 0.35, "efficiency": 0.30, "speed": 0.15, "simplicity": 0.20}

# Detection confidence -> probability the savings materialize as estimated
CONFIDENCE_FACTOR = {"high": 0.9, "medium": 0.6, "low": 0.35}

# Effort rating -> (base implementation cost, cost per affected item)
EFFORT_COST = {
    "low": (5_000.0, 250.0),
    "medium": (25_000.0, 1_000.0),
    "high": (75_000.0, 2_500.0),
}

# Effort rating -> months until savings start landing
TIME_TO_VALUE_MONTHS = {"low": 1, "medium": 3, "high": 9}

# Effort rating -> fixed speed component (faster = higher)
SPEED_SCORE = {"low": 1.0, "medium": 0.6, "high": 0.2}

# Complexity rating -> fixed simplicity component (simpler = higher)
SIMPLICITY_SCORE = {"low": 1.0, "medium": 0.7, "high": 0.4, "very_high": 0.15}

PAYBACK_RATIO_CAP = 10.0  # beyond 10x annual return, more ratio isn't more signal


class WeightError(ValueError):
    pass


def normalize_weights(
    value: Optional[float],
    efficiency: Optional[float],
    speed: Optional[float],
    simplicity: Optional[float] = None,
) -> Dict[str, float]:
    if value is None and efficiency is None and speed is None and simplicity is None:
        return dict(DEFAULT_WEIGHTS)
    weights = {
        "value": DEFAULT_WEIGHTS["value"] if value is None else value,
        "efficiency": DEFAULT_WEIGHTS["efficiency"] if efficiency is None else efficiency,
        "speed": DEFAULT_WEIGHTS["speed"] if speed is None else speed,
        "simplicity": DEFAULT_WEIGHTS["simplicity"] if simplicity is None else simplicity,
    }
    if any(w < 0 for w in weights.values()):
        raise WeightError("weights must be >= 0")
    total = sum(weights.values())
    if total <= 0:
        raise WeightError("at least one weight must be > 0")
    return {k: w / total for k, w in weights.items()}


def _economics(opp: Dict[str, Any]) -> Dict[str, Any]:
    confidence = CONFIDENCE_FACTOR.get(opp["confidence"], 0.5)
    risk_adjusted = opp["estimated_annual_savings"] * confidence

    base, per_item = EFFORT_COST.get(opp["effort"], EFFORT_COST["medium"])
    est_cost = base + per_item * opp.get("affected_count", 1)

    ttv = TIME_TO_VALUE_MONTHS.get(opp["effort"], 3)
    monthly = risk_adjusted / 12
    payback_months = round(ttv + est_cost / monthly, 1) if monthly > 0 else None
    first_year_net = risk_adjusted * max(12 - ttv, 0) / 12 - est_cost
    three_year_net = risk_adjusted * max(36 - ttv, 0) / 12 - est_cost
    payback_ratio = risk_adjusted / est_cost if est_cost > 0 else 0.0

    return {
        "risk_adjusted_annual_savings": round(risk_adjusted, 2),
        "est_implementation_cost": round(est_cost, 2),
        "time_to_value_months": ttv,
        "payback_months": payback_months,
        "first_year_net": round(first_year_net, 2),
        "three_year_net": round(three_year_net, 2),
        "payback_ratio": round(payback_ratio, 2),
    }


def _quadrant(risk_adjusted: float, est_cost: float,
              value_median: float, cost_median: float) -> str:
    high_value = risk_adjusted >= value_median
    low_cost = est_cost <= cost_median
    if high_value and low_cost:
        return "quick_win"
    if high_value:
        return "strategic_bet"
    if low_cost:
        return "fill_in"
    return "deprioritize"


def prioritize(
    opportunities: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Annotates each opportunity with a `priority` block and returns the
    re-ranked list plus portfolio-level stats."""
    weights = weights or dict(DEFAULT_WEIGHTS)
    if not opportunities:
        return {"opportunities": [], "summary": None, "weights": weights}

    economics = [_economics(o) for o in opportunities]

    max_value = max(e["risk_adjusted_annual_savings"] for e in economics)
    max_ratio = max(min(e["payback_ratio"], PAYBACK_RATIO_CAP) for e in economics)
    value_median = median(e["risk_adjusted_annual_savings"] for e in economics)
    cost_median = median(e["est_implementation_cost"] for e in economics)

    ranked = []
    for opp, econ in zip(opportunities, economics):
        value_score = (
            math.log1p(econ["risk_adjusted_annual_savings"]) / math.log1p(max_value)
            if max_value > 0 else 0.0
        )
        efficiency_score = (
            min(econ["payback_ratio"], PAYBACK_RATIO_CAP) / max_ratio
            if max_ratio > 0 else 0.0
        )
        speed_score = SPEED_SCORE.get(opp["effort"], 0.6)
        simplicity_score = SIMPLICITY_SCORE.get(opp.get("complexity", "medium"), 0.7)

        score = 100 * (
            weights["value"] * value_score
            + weights["efficiency"] * efficiency_score
            + weights["speed"] * speed_score
            + weights["simplicity"] * simplicity_score
        )

        annotated = dict(opp)
        annotated["priority"] = {
            **econ,
            "score": round(score, 1),
            "quadrant": _quadrant(
                econ["risk_adjusted_annual_savings"],
                econ["est_implementation_cost"],
                value_median, cost_median,
            ),
            "components": {
                "value": round(value_score, 3),
                "efficiency": round(efficiency_score, 3),
                "speed": round(speed_score, 3),
                "simplicity": round(simplicity_score, 3),
            },
        }
        ranked.append(annotated)

    ranked.sort(key=lambda o: o["priority"]["score"], reverse=True)
    for rank, opp in enumerate(ranked, start=1):
        opp["priority"]["rank"] = rank

    # portfolio stats: how concentrated is the value, in score order?
    total_ra = sum(o["priority"]["risk_adjusted_annual_savings"] for o in ranked)
    count_for_80 = 0
    if total_ra > 0:
        running = 0.0
        for opp in ranked:
            running += opp["priority"]["risk_adjusted_annual_savings"]
            count_for_80 += 1
            if running >= 0.8 * total_ra:
                break

    quadrant_counts: Dict[str, int] = {}
    for opp in ranked:
        q = opp["priority"]["quadrant"]
        quadrant_counts[q] = quadrant_counts.get(q, 0) + 1

    summary = {
        "total_risk_adjusted_annual_savings": round(total_ra, 2),
        "count_for_80_pct_of_value": count_for_80,
        "quadrant_counts": quadrant_counts,
    }
    return {"opportunities": ranked, "summary": summary, "weights": weights}
