"""Portfolio value against time.

Builds a monthly series from the events the platform already records:

  cost      — implementation cost lands in the month a case goes live
  claimed   — self-reported savings entries, cumulative by entry date
  verified  — metric-binding observations: at any month, the verified
              run-rate is the sum of each binding's latest observed
              annualized reduction; cumulative verified value integrates
              that run-rate month by month (evidence only counts from the
              moment it was observed — no retroactive credit)

From those, portfolio ROI over time and a projected break-even point
(extending the current verified run-rate forward, clearly flagged as
projection).
"""
import calendar
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from . import metrics

PROJECTION_MONTHS = 12

YM = Tuple[int, int]


def _ym(d: date) -> YM:
    return (d.year, d.month)


def _ym_str(ym: YM) -> str:
    return f"{ym[0]:04d}-{ym[1]:02d}"


def _next(ym: YM) -> YM:
    year, month = ym
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _end_of_month(ym: YM) -> date:
    return date(ym[0], ym[1], calendar.monthrange(ym[0], ym[1])[1])


def _parse_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def build(cases: List[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    current = _ym(today)

    cost_by_month: Dict[YM, float] = {}
    claimed_by_month: Dict[YM, float] = {}
    # per binding: sorted [(observed_date, annualized_delta)]
    binding_series: List[List[Tuple[date, float]]] = []
    starts: List[YM] = []

    for case in cases:
        # Metered funding: released tranches are the cost record, landing in
        # their release months. Cases without tranches fall back to the
        # estimated cost landing at go-live.
        released = [
            t for t in case.get("funding", {}).get("tranches", [])
            if t["status"] == "released" and t.get("released_at")
        ]
        if released:
            for tranche in released:
                release_date = _parse_date(tranche["released_at"])
                if release_date and tranche["amount"] > 0:
                    key = _ym(release_date)
                    cost_by_month[key] = cost_by_month.get(key, 0) + tranche["amount"]
                    starts.append(key)
        elif case["status"] == "implemented" and case["go_live_date"]:
            go_live = _parse_date(case["go_live_date"])
            if go_live:
                cost = case["estimated_cost"] or 0
                if cost > 0:
                    key = _ym(go_live)
                    cost_by_month[key] = cost_by_month.get(key, 0) + cost
                    starts.append(key)
        for entry in case["savings_entries"]:
            entry_date = _parse_date(entry["entry_date"])
            if entry_date:
                key = _ym(entry_date)
                claimed_by_month[key] = claimed_by_month.get(key, 0) + entry["amount"]
                starts.append(key)
        for binding in case["metric_bindings"]:
            series = []
            for obs in binding["observations"]:
                observed = _parse_date(obs["observed_at"])
                annualized = metrics.annualized_delta(
                    binding["definition"], binding["baseline_value"], obs["value"]
                )
                if observed and annualized is not None:
                    series.append((observed, annualized))
            if series:
                series.sort(key=lambda pair: pair[0])
                binding_series.append(series)
                starts.append(_ym(series[0][0]))

    if not starts:
        return {"months": [], "summary": None}

    def run_rate_at(ym: YM) -> float:
        cutoff = _end_of_month(ym)
        total = 0.0
        for series in binding_series:
            latest = None
            for observed, annualized in series:
                if observed <= cutoff:
                    latest = annualized
                else:
                    break
            if latest is not None:
                total += latest
        return total

    months: List[Dict[str, Any]] = []
    cum_cost = cum_claimed = cum_verified = 0.0
    ym = min(starts)
    while ym <= current:
        cum_cost += cost_by_month.get(ym, 0)
        cum_claimed += claimed_by_month.get(ym, 0)
        run_rate = run_rate_at(ym)
        cum_verified += run_rate / 12
        months.append({
            "month": _ym_str(ym),
            "cumulative_cost": round(cum_cost, 2),
            "cumulative_claimed": round(cum_claimed, 2),
            "cumulative_verified": round(cum_verified, 2),
            "verified_run_rate": round(run_rate, 2),
            "roi_pct": round((cum_verified - cum_cost) / cum_cost * 100, 1)
            if cum_cost > 0 else None,
            "projected": False,
        })
        ym = _next(ym)

    # project the current verified run-rate forward to find break-even
    summary_roi = months[-1]["roi_pct"]
    total_invested = cum_cost
    verified_to_date = cum_verified
    claimed_to_date = cum_claimed
    final_run_rate = months[-1]["verified_run_rate"]

    break_even_month = next(
        (m["month"] for m in months
         if m["cumulative_cost"] > 0 and m["cumulative_verified"] >= m["cumulative_cost"]),
        None,
    )
    if final_run_rate > 0:
        proj_verified = cum_verified
        last = months[-1]["month"]
        ym = _next((int(last[:4]), int(last[5:7])))
        for _ in range(PROJECTION_MONTHS):
            proj_verified += final_run_rate / 12
            months.append({
                "month": _ym_str(ym),
                "cumulative_cost": round(cum_cost, 2),
                "cumulative_claimed": round(cum_claimed, 2),
                "cumulative_verified": round(proj_verified, 2),
                "verified_run_rate": round(final_run_rate, 2),
                "roi_pct": round((proj_verified - cum_cost) / cum_cost * 100, 1)
                if cum_cost > 0 else None,
                "projected": True,
            })
            if break_even_month is None and cum_cost > 0 and proj_verified >= cum_cost:
                break_even_month = _ym_str(ym)
            ym = _next(ym)

    return {
        "months": months,
        "summary": {
            "total_invested": round(total_invested, 2),
            "verified_value_to_date": round(verified_to_date, 2),
            "claimed_value_to_date": round(claimed_to_date, 2),
            "verified_run_rate": round(final_run_rate, 2),
            "portfolio_roi_pct": summary_roi,
            "break_even_month": break_even_month,
            "break_even_projected": bool(
                break_even_month
                and any(m["projected"] and m["month"] == break_even_month for m in months)
            ),
        },
    }
