"""Cost-reduction opportunity detection.

Each rule scans one ingested dataset and emits opportunities with an
estimated annual savings figure. Estimates are deliberately conservative
heuristics — they rank and size opportunities for investigation, they are
not a financial commitment.
"""
import hashlib
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Dict, List

COST_PER_TICKET = 22.0  # blended handling cost assumption per ITSM ticket

# Complexity is distinct from effort: effort approximates labor/cost, complexity
# approximates coordination burden and delivery risk (stakeholders, migrations,
# org change, root-cause uncertainty). Rules assign the intrinsic complexity of
# the play; scale bumps it because big blast radii mean more coordination.
_COMPLEXITY_LEVELS = ["low", "medium", "high", "very_high"]


def _scale_complexity(base: str, affected_count: int) -> str:
    bump = 2 if affected_count >= 75 else 1 if affected_count >= 15 else 0
    idx = min(_COMPLEXITY_LEVELS.index(base) + bump, len(_COMPLEXITY_LEVELS) - 1)
    return _COMPLEXITY_LEVELS[idx]


def _opportunity(
    source: str,
    category: str,
    title: str,
    description: str,
    savings: float,
    effort: str,
    affected: List[str],
    confidence: str,
    complexity: str = "medium",
) -> Dict[str, Any]:
    # Deterministic ID so business cases can link to an opportunity and the
    # link survives server restarts and re-analysis.
    digest = hashlib.sha1(f"{source}|{category}|{title}".encode()).hexdigest()[:10]
    return {
        "id": f"OPP-{digest}",
        "source": source,
        "category": category,
        "title": title,
        "description": description,
        "estimated_annual_savings": round(savings, 2),
        "effort": effort,
        "confidence": confidence,
        "complexity": _scale_complexity(complexity, len(affected)),
        "affected_items": affected[:25],
        "affected_count": len(affected),
    }


# ---------------------------------------------------------------- CMDB rules

def _cmdb_rules(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opps = []
    active = [
        r for r in rows
        if r.get("status", "").lower() in ("active", "operational", "in use", "installed", "live")
    ]

    idle = [
        r for r in active
        if r.get("cpu_utilization_pct") is not None and r["cpu_utilization_pct"] < 5.0
        and (r.get("annual_cost") or 0) > 0
    ]
    if idle:
        savings = sum(r["annual_cost"] for r in idle)
        opps.append(_opportunity(
            "cmdb", "Idle infrastructure",
            f"Decommission {len(idle)} idle servers (<5% CPU)",
            "Servers running below 5% average CPU are candidates for decommissioning "
            "or consolidation. Savings assume full retirement of the asset.",
            savings, "medium", [r["ci_name"] for r in idle], "high", complexity="medium",
        ))

    today = date.today()
    eol = [
        r for r in active
        if r.get("eol_date") and r["eol_date"] < today and (r.get("annual_cost") or 0) > 0
    ]
    if eol:
        # Past-EOL assets typically carry an extended-support premium (~30% of run cost)
        savings = sum(r["annual_cost"] for r in eol) * 0.30
        opps.append(_opportunity(
            "cmdb", "End-of-life risk",
            f"Replace or retire {len(eol)} past-EOL assets",
            "Assets past their end-of-life date incur extended-support premiums and "
            "security exposure. Savings estimate the support premium avoided (~30% of run cost).",
            savings, "high", [r["ci_name"] for r in eol], "medium", complexity="high",
        ))

    by_app_category: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in active:
        if r.get("ci_type", "").lower() == "application" and r.get("application_category"):
            by_app_category[r["application_category"].lower()].append(r)
    for cat, apps in by_app_category.items():
        if len(apps) >= 3:
            costs = sorted((a.get("annual_cost") or 0) for a in apps)
            # consolidate down to the top-2: assume the cheaper overlapping apps are retired
            savings = sum(costs[:-2]) * 0.7
            if savings > 0:
                opps.append(_opportunity(
                    "cmdb", "Application rationalization",
                    f"Consolidate {len(apps)} overlapping '{cat}' applications",
                    f"{len(apps)} applications serve the '{cat}' capability. Consolidating to "
                    "one or two platforms removes duplicate licensing and support effort.",
                    savings, "high", [a["ci_name"] for a in apps], "medium", complexity="high",
                ))

    nonprod = [
        r for r in active
        if r.get("environment", "").lower() in ("dev", "test", "qa", "staging")
        and (r.get("annual_cost") or 0) > 10000
    ]
    if nonprod:
        savings = sum(r["annual_cost"] for r in nonprod) * 0.40
        opps.append(_opportunity(
            "cmdb", "Non-production rightsizing",
            f"Rightsize {len(nonprod)} high-cost non-production systems",
            "Non-production systems costing >$10k/yr can usually be downsized or "
            "scheduled (off outside business hours) for ~40% savings.",
            savings, "low", [r["ci_name"] for r in nonprod], "medium", complexity="low",
        ))
    return opps


# ----------------------------------------------------------------- ERP rules

def _erp_rules(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opps = []
    valid = [r for r in rows if r.get("amount") and r.get("invoice_date")]

    # Duplicate payments: same vendor + same amount within a 10-day window
    seen: Dict[Any, Dict[str, Any]] = {}
    dupes = []
    for r in sorted(valid, key=lambda x: x["invoice_date"]):
        key = (r["vendor"].lower(), r["amount"])
        prior = seen.get(key)
        if prior and (r["invoice_date"] - prior["invoice_date"]) <= timedelta(days=10) \
                and r["invoice_id"] != prior["invoice_id"]:
            dupes.append(r)
        seen[key] = r
    if dupes:
        savings = sum(r["amount"] for r in dupes)
        opps.append(_opportunity(
            "erp", "Duplicate payments",
            f"Recover {len(dupes)} probable duplicate invoices",
            "Invoices with the same vendor and amount within 10 days are likely "
            "duplicates. Savings equal the full recoverable amount.",
            savings, "low", [r["invoice_id"] for r in dupes], "high", complexity="low",
        ))

    # Vendor consolidation: categories with 4+ vendors
    by_category: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in valid:
        by_category[r["category"].lower()][r["vendor"]] += r["amount"]
    for cat, vendors in by_category.items():
        if len(vendors) >= 4:
            spend = sum(vendors.values())
            savings = spend * 0.05  # typical negotiated-rate gain from consolidation
            opps.append(_opportunity(
                "erp", "Vendor consolidation",
                f"Consolidate {len(vendors)} vendors in '{cat}'",
                f"Spend of ${spend:,.0f} in '{cat}' is split across {len(vendors)} vendors. "
                "Consolidating to preferred vendors typically yields ~5% via volume pricing.",
                savings, "medium", sorted(vendors), "medium", complexity="high",
            ))

    # Maverick spend: invoices with no PO
    no_po = [r for r in valid if not r.get("po_number")]
    if no_po:
        spend = sum(r["amount"] for r in no_po)
        if spend > 0:
            opps.append(_opportunity(
                "erp", "Maverick spend",
                f"Bring {len(no_po)} off-PO invoices under procurement control",
                f"${spend:,.0f} was invoiced without a purchase order. Routing this through "
                "procurement typically saves ~3% via negotiated rates and approval control.",
                spend * 0.03, "medium", [r["invoice_id"] for r in no_po], "medium", complexity="medium",
            ))
    return opps


# --------------------------------------------------------------- Cloud rules

def _cloud_rules(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opps = []
    running = [r for r in rows if r.get("state", "").lower() in ("running", "active", "in-use")]

    idle = [
        r for r in running
        if r.get("avg_cpu_pct") is not None and r["avg_cpu_pct"] < 5.0
        and (r.get("monthly_cost") or 0) > 0
    ]
    if idle:
        savings = sum(r["monthly_cost"] for r in idle) * 12
        opps.append(_opportunity(
            "cloud", "Idle cloud resources",
            f"Terminate {len(idle)} idle cloud resources (<5% CPU)",
            "Running resources averaging under 5% CPU are doing no useful work. "
            "Savings assume termination.",
            savings, "low", [r["resource_id"] for r in idle], "high", complexity="low",
        ))

    oversized = [
        r for r in running
        if r.get("avg_cpu_pct") is not None and 5.0 <= r["avg_cpu_pct"] < 20.0
        and (r.get("monthly_cost") or 0) > 0
    ]
    if oversized:
        savings = sum(r["monthly_cost"] for r in oversized) * 12 * 0.40
        opps.append(_opportunity(
            "cloud", "Rightsizing",
            f"Downsize {len(oversized)} over-provisioned instances",
            "Resources at 5-20% CPU can usually drop one or two instance sizes "
            "(~40% of cost).",
            savings, "low", [r["resource_id"] for r in oversized], "high", complexity="low",
        ))

    unattached = [
        r for r in rows
        if r.get("state", "").lower() in ("unattached", "available", "orphaned")
        and (r.get("monthly_cost") or 0) > 0
    ]
    if unattached:
        savings = sum(r["monthly_cost"] for r in unattached) * 12
        opps.append(_opportunity(
            "cloud", "Orphaned storage",
            f"Delete {len(unattached)} unattached volumes/IPs",
            "Unattached volumes and idle allocations bill continuously with no consumer. "
            "Snapshot then delete.",
            savings, "low", [r["resource_id"] for r in unattached], "high", complexity="low",
        ))

    stopped_billed = [
        r for r in rows
        if r.get("state", "").lower() == "stopped" and (r.get("monthly_cost") or 0) > 50
    ]
    if stopped_billed:
        savings = sum(r["monthly_cost"] for r in stopped_billed) * 12 * 0.8
        opps.append(_opportunity(
            "cloud", "Stopped-but-billing",
            f"Clean up {len(stopped_billed)} stopped resources still accruing cost",
            "Stopped instances still bill for attached storage and reservations. "
            "Deallocate or delete after review.",
            savings, "low", [r["resource_id"] for r in stopped_billed], "medium", complexity="low",
        ))
    return opps


# ---------------------------------------------------------------- ITSM rules

def _itsm_rules(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    opps = []

    requests_by_cat: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("ticket_type", "").lower() in ("request", "service request"):
            requests_by_cat[r["category"].lower()].append(r)
    for cat, tickets in requests_by_cat.items():
        if len(tickets) >= 10:
            res_times = [t["resolution_minutes"] for t in tickets if t.get("resolution_minutes")]
            avg_res = sum(res_times) / len(res_times) if res_times else 0
            # high-volume, quick-resolution requests are prime automation candidates
            if avg_res and avg_res <= 60:
                annualized = len(tickets) * COST_PER_TICKET * 4  # assume sample is ~1 quarter
                opps.append(_opportunity(
                    "itsm", "Automation candidate",
                    f"Automate '{cat}' service requests ({len(tickets)} in period)",
                    f"'{cat}' requests resolve in ~{avg_res:.0f} min on average — repetitive, "
                    "low-complexity work suited to self-service automation. Savings assume "
                    f"${COST_PER_TICKET:.0f}/ticket handling cost, annualized.",
                    annualized * 0.8, "medium", [t["ticket_id"] for t in tickets], "medium", complexity="medium",
                ))

    incidents_by_ci: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("ticket_type", "").lower() == "incident" and r.get("ci_name"):
            incidents_by_ci[r["ci_name"]].append(r)
    hotspots = {ci: t for ci, t in incidents_by_ci.items() if len(t) >= 5}
    if hotspots:
        total = sum(len(t) for t in hotspots.values())
        res_costs = total * COST_PER_TICKET * 4 * 1.5  # incidents cost more than requests
        opps.append(_opportunity(
            "itsm", "Incident hotspot",
            f"Remediate {len(hotspots)} CIs generating repeat incidents",
            f"{total} incidents in the period trace to {len(hotspots)} configuration items: "
            f"{', '.join(sorted(hotspots))}. Root-cause remediation removes the recurring "
            "handling cost and downtime.",
            res_costs * 0.7, "high", sorted(hotspots), "medium", complexity="high",
        ))
    return opps


RULES = {
    "cmdb": _cmdb_rules,
    "erp": _erp_rules,
    "cloud": _cloud_rules,
    "itsm": _itsm_rules,
}


def analyze(datasets: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    opportunities: List[Dict[str, Any]] = []
    for source_type, rows in datasets.items():
        rule = RULES.get(source_type)
        if rule and rows:
            opportunities.extend(rule(rows))
    opportunities.sort(key=lambda o: o["estimated_annual_savings"], reverse=True)
    return opportunities
