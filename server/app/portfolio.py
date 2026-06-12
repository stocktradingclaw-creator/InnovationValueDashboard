"""Value diagnostic for an existing initiative portfolio.

Ingest a PMO-style export (initiatives with budgets, claimed benefits,
status, dates, measured benefits where they exist) and diagnose where the
portfolio leaks value: unverified benefit claims, realization shortfalls,
weak ROI, overruns, stalled or parked work, concentration risk, and
over-reliance on soft benefits.

Statuses are matched loosely: in_flight / in flight / active / build,
live / complete / delivered, on_hold / paused / blocked.
"""
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List, Optional

PAYBACK_YEARS_THRESHOLD = 3.0
REALIZATION_SHORTFALL = 0.6
UNVERIFIED_GRACE_MONTHS = 3
STALLED_MONTHS = 12
CONCENTRATION_SHARE = 0.4
SOFT_RELIANCE_SHARE = 0.5

SEVERITY_DEDUCTION = {"high": 15, "medium": 8, "low": 4}


def _status(row: Dict[str, Any]) -> str:
    raw = (row.get("status") or "").lower()
    if any(k in raw for k in ("hold", "paus", "block")):
        return "on_hold"
    if any(k in raw for k in ("live", "complete", "deliver", "done", "closed")):
        return "live"
    return "in_flight"


def _months_since(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return max((today.year - d.year) * 12 + (today.month - d.month), 0)


def _finding(
    category: str, severity: str, title: str, description: str,
    affected: List[str], value_impact: float,
) -> Dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "affected_initiatives": affected[:25],
        "affected_count": len(affected),
        "value_impact": round(value_impact, 2),
    }


def diagnose(rows: List[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    findings: List[Dict[str, Any]] = []

    total_budget = sum(r.get("budget") or 0 for r in rows)
    total_spend = sum(r.get("spend_to_date") or 0 for r in rows)
    total_claimed = sum(r.get("claimed_annual_benefit") or 0 for r in rows)
    total_measured = sum(r.get("measured_annual_benefit") or 0 for r in rows)

    # --- unverified benefits: live long enough to measure, nothing measured
    unverified = [
        r for r in rows
        if _status(r) == "live"
        and (r.get("claimed_annual_benefit") or 0) > 0
        and not (r.get("measured_annual_benefit") or 0)
        and (_months_since(r.get("go_live_date"), today) or 0) >= UNVERIFIED_GRACE_MONTHS
    ]
    if unverified:
        at_stake = sum(r["claimed_annual_benefit"] for r in unverified)
        findings.append(_finding(
            "Unverified benefits", "high",
            f"{len(unverified)} live initiatives claim ${at_stake:,.0f}/yr with no measurement",
            f"These initiatives have been live for {UNVERIFIED_GRACE_MONTHS}+ months but no "
            "benefit has ever been measured. Until measured, this value exists only on paper. "
            "Stand up metric bindings or a measurement plan for each.",
            [r["name"] for r in unverified], at_stake,
        ))

    # --- realization shortfall: measured but far below claim
    shortfall = [
        r for r in rows
        if (r.get("measured_annual_benefit") or 0) > 0
        and (r.get("claimed_annual_benefit") or 0) > 0
        and r["measured_annual_benefit"] < r["claimed_annual_benefit"] * REALIZATION_SHORTFALL
    ]
    if shortfall:
        gap = sum(r["claimed_annual_benefit"] - r["measured_annual_benefit"] for r in shortfall)
        findings.append(_finding(
            "Realization shortfall", "high",
            f"{len(shortfall)} initiatives realize <{REALIZATION_SHORTFALL:.0%} of claimed benefit",
            f"Measured benefits run ${gap:,.0f}/yr below claims. Either the benefit case was "
            "inflated or adoption stalled — investigate before approving similar cases.",
            [r["name"] for r in shortfall], gap,
        ))

    # --- weak ROI: payback beyond threshold at claimed benefit
    weak = [
        r for r in rows
        if _status(r) != "live"
        and (r.get("claimed_annual_benefit") or 0) > 0
        and (r.get("budget") or 0) > 0
        and r["budget"] / r["claimed_annual_benefit"] > PAYBACK_YEARS_THRESHOLD
    ]
    if weak:
        spend_exposed = sum((r.get("budget") or 0) - (r.get("spend_to_date") or 0) for r in weak)
        findings.append(_finding(
            "Weak ROI", "medium",
            f"{len(weak)} in-flight initiatives have >{PAYBACK_YEARS_THRESHOLD:.0f}-year paybacks",
            "Even taking the benefit claims at face value, these initiatives pay back slowly. "
            f"${max(spend_exposed, 0):,.0f} of remaining budget could be rescoped or redirected "
            "to faster-payback work.",
            [r["name"] for r in weak], max(spend_exposed, 0),
        ))

    # --- overruns
    overruns = [
        r for r in rows
        if (r.get("budget") or 0) > 0 and (r.get("spend_to_date") or 0) > r["budget"]
    ]
    if overruns:
        overage = sum(r["spend_to_date"] - r["budget"] for r in overruns)
        findings.append(_finding(
            "Budget overrun", "medium",
            f"{len(overruns)} initiatives are over budget by ${overage:,.0f}",
            "Spend has exceeded approved budget. Re-baseline the business case — benefits "
            "calculated against the original budget overstate ROI.",
            [r["name"] for r in overruns], overage,
        ))

    # --- stalled in-flight work
    stalled = [
        r for r in rows
        if _status(r) == "in_flight"
        and (_months_since(r.get("start_date"), today) or 0) >= STALLED_MONTHS
        and not r.get("go_live_date")
    ]
    if stalled:
        sunk = sum(r.get("spend_to_date") or 0 for r in stalled)
        findings.append(_finding(
            "Stalled delivery", "high",
            f"{len(stalled)} initiatives in flight {STALLED_MONTHS}+ months without go-live",
            f"${sunk:,.0f} spent with no live date. Every month of delay defers the claimed "
            "benefit; stop, descope, or reset these.",
            [r["name"] for r in stalled], sunk,
        ))

    # --- zombies: on hold with money sunk
    zombies = [
        r for r in rows
        if _status(r) == "on_hold" and (r.get("spend_to_date") or 0) > 0
    ]
    if zombies:
        sunk = sum(r["spend_to_date"] for r in zombies)
        findings.append(_finding(
            "Parked spend", "medium",
            f"{len(zombies)} on-hold initiatives have ${sunk:,.0f} sunk",
            "Paused work decays: teams move on, integrations drift. Decide to restart or "
            "formally close and write off.",
            [r["name"] for r in zombies], sunk,
        ))

    # --- concentration: one initiative dominates the claimed value
    if total_claimed > 0:
        top = max(rows, key=lambda r: r.get("claimed_annual_benefit") or 0)
        top_share = (top.get("claimed_annual_benefit") or 0) / total_claimed
        if top_share > CONCENTRATION_SHARE:
            findings.append(_finding(
                "Concentration risk", "low",
                f"'{top['name']}' carries {top_share:.0%} of all claimed value",
                "The portfolio's value case depends heavily on one initiative. If it slips "
                "or under-delivers, the portfolio misses. Protect it with the strongest "
                "measurement discipline and de-risk with quicker wins.",
                [top["name"]], top.get("claimed_annual_benefit") or 0,
            ))

    # --- soft benefit reliance
    soft_claimed = sum(
        r.get("claimed_annual_benefit") or 0 for r in rows
        if (r.get("benefit_type") or "").lower() == "soft"
    )
    if total_claimed > 0 and soft_claimed / total_claimed > SOFT_RELIANCE_SHARE:
        findings.append(_finding(
            "Soft benefit reliance", "medium",
            f"{soft_claimed / total_claimed:.0%} of claimed value is soft benefits",
            "Productivity and risk-avoidance claims dominate the value case. These rarely "
            "survive measurement at face value — restate them with hard proxies or discount.",
            [r["name"] for r in rows if (r.get("benefit_type") or "").lower() == "soft"],
            soft_claimed,
        ))

    # --- duplicate scope: several non-live initiatives in the same category
    by_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if _status(r) == "in_flight" and r.get("category"):
            by_category[r["category"].lower()].append(r)
    for cat, group in by_category.items():
        if len(group) >= 2:
            budgets = sum(r.get("budget") or 0 for r in group)
            findings.append(_finding(
                "Overlapping scope", "low",
                f"{len(group)} in-flight initiatives in '{cat}'",
                f"${budgets:,.0f} of budget targets the same capability. Check for duplicate "
                "scope and consolidate delivery teams or platforms.",
                [r["name"] for r in group], budgets * 0.2,
            ))

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (severity_rank[f["severity"]], -f["value_impact"]))

    score = 100
    for f in findings:
        score -= SEVERITY_DEDUCTION[f["severity"]]
    score = max(score, 5)

    return {
        "health_score": score,
        "stats": {
            "initiatives": len(rows),
            "total_budget": round(total_budget, 2),
            "total_spend_to_date": round(total_spend, 2),
            "total_claimed_annual_benefit": round(total_claimed, 2),
            "total_measured_annual_benefit": round(total_measured, 2),
            "verification_ratio": round(total_measured / total_claimed, 3)
            if total_claimed > 0 else None,
        },
        "findings": findings,
    }
