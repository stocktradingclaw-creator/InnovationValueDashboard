"""Continuous portfolio telemetry: one initiative entity (ideas->cases) seen
through many lenses — balance, funnel, funding, value realization — plus the
single value roll-up (pool -> gap -> initiative -> realized) so nothing
double-counts."""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import db, maturity

ONN = ["old", "now", "new"]
FUNNEL = ["idea", "validated", "pilot", "scaling", "scaled"]
_STAGE_TO_FUNNEL = {"draft": "validated", "proposed": "validated", "experiment": "validated",
                    "approved": "pilot", "in_delivery": "pilot", "live": "scaling",
                    "value_realized": "scaled", "scale": "scaled"}
DIGITAL_DIMS = [
    ("cloud", "Cloud & infrastructure"), ("data", "Data platform"),
    ("aiml", "AI/ML readiness"), ("engineering", "Engineering talent"),
    ("archdebt", "Architecture debt"),
]


def strategy_context() -> Dict[str, Any]:
    raw = db.meta_get("strategy_context")
    if raw:
        return json.loads(raw)
    ctx = {"disruption_current": 3, "susceptibility": 3,
           "ambition": "Grow the core while building two transformational bets to scale.",
           "notes": "", "sources": "",
           "target_onn": {"old": 0.3, "now": 0.5, "new": 0.2}}
    db.meta_set("strategy_context", json.dumps(ctx))
    return ctx


def save_strategy_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
    db.meta_set("strategy_context", json.dumps(ctx))
    return ctx


def value_pools() -> List[Dict[str, Any]]:
    raw = db.meta_get("value_pools")
    if raw:
        return json.loads(raw)
    pools = [
        {"key": "enterprise", "name": "Enterprise value", "low": 2000000, "high": 6000000,
         "assumptions": "Efficiency + growth captured inside our own P&L (editable placeholder)",
         "dimensions": ["velocity", "governance", "portfolio", "cloud", "data"]},
        {"key": "industry", "name": "Industry / ecosystem", "low": 1000000, "high": 4000000,
         "assumptions": "Value from partners, standards, and shared infrastructure",
         "dimensions": ["strategy", "scaling"]},
        {"key": "customer", "name": "Customer value", "low": 800000, "high": 2500000,
         "assumptions": "Willingness-to-pay uplift and churn reduction",
         "dimensions": ["insight", "culture"]},
        {"key": "society", "name": "Society", "low": 200000, "high": 1000000,
         "assumptions": "Risk, sustainability, and access externalities",
         "dimensions": ["talent"]},
    ]
    db.meta_set("value_pools", json.dumps(pools))
    return pools


def _onn(case: Dict[str, Any]) -> str:
    # heuristic default, overridable per-case via 'onn' key in the future:
    # cost-out on the legacy core = old; h3 bets = new; the rest = now
    if case.get("horizon") == "h3":
        return "new"
    lo = case.get("linked_opportunity") or {}
    if (case.get("benefit_type") or "") == "cost_reduction" or \
       "idle" in (lo.get("category") or "").lower():
        return "old"
    return "now"


def _days_since(ts: Optional[str]) -> Optional[int]:
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - t).days, 0)
    except ValueError:
        return None


def snapshot() -> Dict[str, Any]:
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    ctx = strategy_context()

    # ---- A: old/now/new balance vs target ----
    alloc = {k: {"spend": 0.0, "count": 0} for k in ONN}
    for c in cases:
        if c["stage"] == "closed":
            continue
        k = _onn(c)
        alloc[k]["count"] += 1
        alloc[k]["spend"] += (c.get("funding") or {}).get("released", 0) or 0
    spend_total = sum(a["spend"] for a in alloc.values()) or 1.0
    balance = []
    drift = False
    for k in ONN:
        share = alloc[k]["spend"] / spend_total
        target = ctx["target_onn"].get(k, 0.33)
        if abs(share - target) > 0.15:
            drift = True
        balance.append({"horizon": k, "share": round(share, 3), "target": target,
                        "spend": round(alloc[k]["spend"], 2), "count": alloc[k]["count"],
                        "variance": round(share - target, 3)})

    # ---- B: funnel, conversions, purgatory ----
    threshold = int(db.meta_get("purgatory_days") or 45)
    stages = {"idea": len([i for i in ideas if i["status"] not in ("declined",)])}
    for f in FUNNEL[1:]:
        stages[f] = 0
    killed = 0
    purgatory = []
    for c in cases:
        if c["stage"] == "closed":
            killed += 1
            continue
        f = _STAGE_TO_FUNNEL.get(c["stage"], "validated")
        stages[f] += 1
        if f == "pilot":
            age = _days_since(c.get("submitted_at"))
            if age is not None and age > threshold:
                purgatory.append({"id": c["id"], "title": c["title"], "days": age})
    conversions = []
    for a, b in zip(FUNNEL, FUNNEL[1:]):
        downstream = sum(stages[x] for x in FUNNEL[FUNNEL.index(b):])
        base = stages[a] + downstream
        conversions.append({"from": a, "to": b,
                            "rate": round(downstream / base, 2) if base else None})

    # ---- F: funding mechanics ----
    committed = sum((c.get("funding") or {}).get("planned", 0) for c in cases)
    released = sum((c.get("funding") or {}).get("released", 0) for c in cases)
    gate_queue = []
    for c in cases:
        for t in (c.get("funding") or {}).get("tranches", []):
            if t.get("status") != "released":
                age = _days_since(c.get("submitted_at")) or 0
                gate_queue.append({"case_id": c["id"], "title": c["title"],
                                   "tranche": t.get("label"), "amount": t.get("amount"),
                                   "milestone": t.get("milestone"),
                                   "overdue": age > threshold})
    kills_by_stage: Dict[str, int] = {}
    for c in cases:
        for e in c.get("experiments", []):
            if e.get("outcome") == "kill":
                kills_by_stage["validated"] = kills_by_stage.get("validated", 0) + 1
    if killed:
        kills_by_stage["pilot"] = kills_by_stage.get("pilot", 0) + max(
            killed - kills_by_stage.get("validated", 0), 0)

    # ---- C: one value roll-up: pool -> gap -> initiative -> realized ----
    pools = value_pools()
    ws = maturity.waves()
    gap_dims = (maturity.wave_summary(ws[-1]["id"])["dimensions"] if ws else [])
    invested = released
    realized_claimed = sum(e["amount"] for c in cases for e in c.get("savings_entries", []))
    realized_verified = sum((b.get("annualized_delta") or 0)
                            for c in cases for b in c.get("metric_bindings", []))
    rollup = []
    for p in pools:
        gaps = [d for d in gap_dims if d["key"] in p["dimensions"] and d.get("value_high")]
        rollup.append({**p,
                       "gaps_value_low": round(sum(d["value_low"] or 0 for d in gaps), 2),
                       "gaps_value_high": round(sum(d["value_high"] or 0 for d in gaps), 2),
                       "gap_names": [d["name"] for d in gaps]})
    trapped_low = sum(p["low"] for p in pools)
    trapped_high = sum(p["high"] for p in pools)

    # ---- E: digital-core sub-score gates scaling ----
    digital = None
    weak_dims: List[str] = []
    if ws:
        dd = [d for d in maturity.wave_summary(ws[-1]["id"])["dimensions"]
              if d["key"] in {k for k, _ in DIGITAL_DIMS}]
        scored = [d for d in dd if d["calibrated"] is not None]
        if scored:
            digital = round(sum(d["calibrated"] for d in scored) / len(scored), 2)
            weak_dims = [d["name"] for d in scored if d["calibrated"] < 3]
    scaling_at_risk = [{"id": c["id"], "title": c["title"], "blocked_on": weak_dims}
                      for c in cases
                      if _STAGE_TO_FUNNEL.get(c["stage"]) in ("scaling", "pilot")
                      and weak_dims] if weak_dims else []

    return {
        "strategy_context": ctx,
        "balance": {"rows": balance, "drift_alert": drift, "total_spend": round(spend_total, 2)},
        "funnel": {"stages": stages, "killed": killed, "conversions": conversions,
                   "purgatory_threshold_days": threshold, "purgatory": purgatory},
        "funding": {"committed": round(committed, 2), "released": round(released, 2),
                    "gate_queue": gate_queue, "kills_by_stage": kills_by_stage,
                    "kill_note": "early kills are a healthy-funnel signal"},
        "value": {"pools": rollup, "trapped_low": trapped_low, "trapped_high": trapped_high,
                  "invested": round(invested, 2),
                  "realized_claimed": round(realized_claimed, 2),
                  "realized_verified": round(realized_verified, 2),
                  "achievement_gap": round(invested - realized_claimed - realized_verified, 2)},
        "digital_core": {"score": digital, "weak_dimensions": weak_dims,
                         "scaling_at_risk": scaling_at_risk},
    }


def ensure_digital_dims() -> None:
    fw = maturity.get_framework()
    have = {d["key"] for d in fw["dimensions"]}
    changed = False
    for k, n in DIGITAL_DIMS:
        if k not in have:
            fw["dimensions"].append({"key": k, "name": n, "description":
                                     f"Digital core: {n.lower()}", "target": 4,
                                     "weight": "critical" if k in ("data", "aiml") else "important",
                                     "rubric": maturity._rubric(n), "group": "digital-core"})
            changed = True
    if changed:
        maturity.save_framework(fw)
