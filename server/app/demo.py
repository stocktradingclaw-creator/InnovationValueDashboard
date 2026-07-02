"""Demo studio: customize the portfolio for a client presentation, safely.

Pick an industry (and client name) and generate a proposed portfolio of
strategic initiatives + ideas tailored to them. Generation uses Claude when an
API key is configured; otherwise deterministic industry templates. Every
generated idea flows through the normal triage pipeline, so the whole platform
lights up with client-relevant content.

Safety: before generating, the SQLite file is snapshotted to a sidecar
baseline. "Revert to baseline" restores that exact file — no orphaned demo
records, no bloat carried into the next presentation. One demo active at a
time.
"""
import json
import os
import shutil
from typing import Any, Dict, List, Optional

from . import db

DEMO_META_KEY = "demo_active"

INDUSTRIES = [
    "healthcare", "financial services", "retail", "manufacturing",
    "insurance", "technology", "public sector",
]


class DemoError(ValueError):
    pass


def _baseline_path() -> str:
    return db._db_path() + ".baseline"


def status() -> Optional[Dict[str, Any]]:
    raw = db.meta_get(DEMO_META_KEY)
    return json.loads(raw) if raw else None


def snapshot() -> None:
    if status() is not None:
        raise DemoError("A demo portfolio is already active — revert to baseline first")
    db.dataset_meta()  # ensures the DB file exists before copying
    shutil.copyfile(db._db_path(), _baseline_path())


def mark_active(client: str, industry: str, generated_by: str,
                initiatives: int, ideas: int) -> Dict[str, Any]:
    import datetime
    info = {
        "client": client,
        "industry": industry,
        "generated_by": generated_by,
        "initiatives": initiatives,
        "ideas": ideas,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    db.meta_set(DEMO_META_KEY, json.dumps(info))
    return info


def revert() -> Dict[str, Any]:
    info = status()
    if info is None:
        raise DemoError("No demo portfolio is active")
    baseline = _baseline_path()
    if not os.path.exists(baseline):
        raise DemoError("Baseline snapshot is missing — cannot revert safely")
    shutil.copyfile(baseline, db._db_path())
    os.remove(baseline)
    # the restored file predates the demo, so demo_active is gone with it
    return info


# ------------------------------------------------------------------ templates

def _t(name: str, objective: str, ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"name": name, "objective": objective, "ideas": ideas}


def _idea(title: str, description: str, category: str, benefit_type: str,
          benefit: float, beneficiary: str, pain: str) -> Dict[str, Any]:
    return {
        "title": title, "description": description, "category": category,
        "benefit_type": benefit_type, "estimated_annual_benefit": benefit,
        "beneficiary": beneficiary, "pain_point": pain,
    }


_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "healthcare": [
        _t("Clinical time back to care", "Give clinicians hours back by removing administrative drag.", [
            _idea("Ambient clinical documentation", "Auto-draft encounter notes from the visit so clinicians stop typing after hours.",
                  "clinical productivity", "experience", 1800000, "1,200 clinicians", "Two hours of after-hours charting per clinician per day"),
            _idea("Prior-authorization automation", "Auto-assemble and submit prior-auth packets from the EHR.",
                  "process automation", "cost_reduction", 650000, "Revenue cycle team", "Manual prior-auths delay care and burn staff hours"),
        ]),
        _t("Smarter patient flow", "Reduce waits and no-shows across the network.", [
            _idea("No-show prediction and smart overbooking", "Predict likely no-shows and offer released slots to the waitlist automatically.",
                  "patient access", "revenue_growth", 900000, "Patients waiting for appointments", "Three-week waits while 12% of slots go unused"),
            _idea("Discharge readiness dashboard", "Real-time discharge blockers so beds turn over on time.",
                  "capacity", "cost_reduction", 750000, "Bed management + nursing", "Discharged-but-waiting patients hold beds for hours"),
        ]),
        _t("Resilient cost base", "Cut run-rate cost without touching care quality.", [
            _idea("Imaging equipment utilization", "Instrument scanner idle time and consolidate underused modalities.",
                  "asset utilization", "cost_reduction", 500000, "Radiology operations", "Scanners idle 40% of scheduled hours across sites"),
            _idea("Clinical supply standardization", "Standardize high-variance supply items across physicians.",
                  "supply chain", "cost_reduction", 1200000, "Supply chain + OR teams", "Same procedure, 4x cost variance by physician preference"),
        ]),
    ],
    "financial services": [
        _t("Frictionless onboarding", "Cut time-to-account and abandonment.", [
            _idea("KYC document intelligence", "Auto-extract and verify onboarding documents; humans handle exceptions only.",
                  "client onboarding", "cost_reduction", 1400000, "Operations + new clients", "Five-day onboarding with 30% application abandonment"),
            _idea("Instant limit decisions", "Pre-approved credit decisions in-session using existing bureau data.",
                  "lending", "revenue_growth", 2200000, "Retail lending applicants", "Customers drop off during 48-hour decision waits"),
        ]),
        _t("Fight financial crime smarter", "Higher catch rates, fewer false positives.", [
            _idea("Alert triage copilot", "Rank and pre-document AML alerts so investigators start with the story, not the search.",
                  "financial crime", "cost_reduction", 1800000, "AML investigation team", "94% of alerts are false positives but each takes an hour"),
            _idea("Fraud pattern replay", "Replay confirmed fraud patterns against the last 90 days nightly.",
                  "fraud", "risk_avoidance", 900000, "Fraud operations", "New fraud patterns run for weeks before rules catch up"),
        ]),
        _t("Advisor productivity", "More client time, less prep time.", [
            _idea("Meeting prep briefs", "Auto-generated client briefs: positions, life events, next best actions.",
                  "wealth management", "revenue_growth", 1100000, "600 advisors", "Advisors spend 90 minutes prepping each review meeting"),
        ]),
    ],
    "retail": [
        _t("Inventory that sells", "Right product, right store, less markdown.", [
            _idea("Markdown optimization", "Store-level markdown timing from sell-through curves instead of chain-wide calendars.",
                  "merchandising", "cost_reduction", 3200000, "Merchandising team", "Chain-wide markdowns give away margin in stores that would sell through"),
            _idea("Shelf-gap computer vision", "Detect out-of-stocks from existing cameras and dispatch restock tasks.",
                  "store operations", "revenue_growth", 1900000, "Store associates + shoppers", "4% of sales lost to items in the back room but not on the shelf"),
        ]),
        _t("Service without queues", "Move routine contacts to instant self-service.", [
            _idea("Order-status deflection", "Self-service order tracking and modification for the top 5 contact reasons.",
                  "customer service", "cost_reduction", 800000, "Contact center + customers", "60% of contacts are 'where is my order'"),
        ]),
        _t("Supply chain visibility", "Know where everything is, act before it's late.", [
            _idea("Late-shipment early warning", "Predict DC-to-store delays and reroute before shelves gap.",
                  "logistics", "cost_reduction", 1100000, "Supply chain planners", "Store managers learn about late trucks when they don't arrive"),
        ]),
    ],
    "manufacturing": [
        _t("Zero unplanned downtime", "Predict failures before the line stops.", [
            _idea("Vibration-based predictive maintenance", "Sensor anomaly detection on rotating equipment with auto-generated work orders.",
                  "maintenance", "cost_reduction", 2400000, "Plant maintenance teams", "Unplanned line stops cost $18k/hour and average 9 hours/month"),
            _idea("Digital andon with root-cause capture", "Structured stop-reason capture at the line feeding a live Pareto.",
                  "operations", "cost_reduction", 600000, "Line supervisors", "Stop reasons live in operators' heads; the same faults recur"),
        ]),
        _t("First-pass quality", "Catch defects at the station, not the customer.", [
            _idea("Inline vision inspection", "Camera inspection at critical stations with automatic containment.",
                  "quality", "cost_reduction", 1500000, "Quality + warranty teams", "Escaped defects trigger six-figure warranty and recall exposure"),
        ]),
        _t("Energy productivity", "Same output, less energy.", [
            _idea("Compressed-air leak program", "Ultrasonic leak detection with tracked repair savings.",
                  "energy", "cost_reduction", 400000, "Facilities", "Compressed air is the plant's most expensive utility and 30% leaks away"),
        ]),
    ],
    "default": [
        _t("Operational efficiency", "Remove manual drag from core operations.", [
            _idea("Intelligent document processing", "Auto-extract data from inbound documents into core systems.",
                  "process automation", "cost_reduction", 900000, "Back-office teams", "Rekeying documents consumes thousands of hours"),
            _idea("Service request automation", "Self-service for the top recurring internal requests.",
                  "service automation", "cost_reduction", 400000, "Employees + service desk", "Routine requests take days for hour-sized tasks"),
        ]),
        _t("Customer experience step-change", "Faster answers, fewer handoffs.", [
            _idea("Customer 360 for frontline teams", "One view of the customer at every touchpoint.",
                  "customer experience", "experience", 1200000, "Frontline service teams", "Agents juggle five systems while customers wait"),
        ]),
        _t("Data-driven decisions", "Trusted numbers everywhere decisions happen.", [
            _idea("Self-serve analytics for operations", "Governed dashboards replacing spreadsheet cottage industry.",
                  "analytics", "cost_reduction", 500000, "Operations leaders", "Each team maintains conflicting spreadsheet versions of the truth"),
        ]),
    ],
}


TARGET_IDEAS = 10

_FILLER_IDEAS = [
    _idea("GenAI knowledge assistant", "Answer policy, product, and process questions from internal documentation instantly.",
          "knowledge management", "cost_reduction", 700000, "All employees", "Experts interrupted daily for answers that live in documents"),
    _idea("Contract intelligence", "Extract obligations, renewal dates, and risk clauses from executed contracts automatically.",
          "legal operations", "risk_avoidance", 450000, "Legal + procurement", "Renewals and obligations are missed because contracts sit unread"),
    _idea("Churn early-warning signals", "Score accounts weekly on engagement decline and trigger save plays.",
          "customer retention", "revenue_growth", 1600000, "Account managers", "Churn is discovered at renewal, when it is too late to act"),
    _idea("Automated management reporting", "Generate the monthly operations pack directly from source systems.",
          "reporting", "cost_reduction", 350000, "Finance + ops analysts", "A week of every month is spent assembling slides by hand"),
    _idea("Employee onboarding automation", "Provision access, equipment, and training paths from a single start event.",
          "hr operations", "experience", 300000, "New hires + IT + HR", "New starters wait days for access while tickets crawl"),
    _idea("Sustainability data platform", "Automate ESG metric collection for regulatory reporting and target tracking.",
          "sustainability", "strategic", 500000, "ESG + finance teams", "Regulatory ESG reporting is a quarterly manual scramble"),
]


def _template_portfolio(industry: Optional[str], client: str) -> Dict[str, Any]:
    key = (industry or "").strip().lower()
    template = _TEMPLATES.get(key)
    if template is None:
        template = next(
            (t for k, t in _TEMPLATES.items() if k != "default" and key and k in key),
            _TEMPLATES["default"],
        )
    initiatives = []
    ideas = []
    for index, initiative in enumerate(template):
        initiatives.append({
            "name": initiative["name"],
            "objective": f"{initiative['objective']} (proposed for {client})",
        })
        for idea in initiative["ideas"]:
            ideas.append({**idea, "initiative_index": index})
    # top up to exactly TARGET_IDEAS with the generic pool, cycling initiatives
    titles = {i["title"] for i in ideas}
    for filler_index, filler in enumerate(_FILLER_IDEAS):
        if len(ideas) >= TARGET_IDEAS:
            break
        if filler["title"] in titles:
            continue
        ideas.append({**filler, "initiative_index": filler_index % len(initiatives)})
    return {"initiatives": initiatives, "ideas": ideas[:TARGET_IDEAS], "generated_by": "template"}


def build_portfolio(industry: Optional[str], client: Optional[str],
                    notes: Optional[str] = None) -> Dict[str, Any]:
    """Returns {initiatives: [{name, objective}], ideas: [...], generated_by}.
    Provide a client, an industry, or both. With a client, generation is
    grounded in the company's publicly stated strategy (researched via web
    search when available); industry-only requests ground in the latest major
    trends in that industry."""
    label = (client or "").strip() or f"{(industry or 'cross-industry').strip().title()} prospect"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _template_portfolio(industry, label)

    import anthropic
    from pydantic import BaseModel, Field
    from typing import List as TList

    class DemoInitiative(BaseModel):
        name: str
        objective: str

    class DemoIdea(BaseModel):
        title: str
        description: str = Field(description="2-3 sentences: problem, change, who benefits")
        category: str
        benefit_type: str = Field(description="cost_reduction | revenue_growth | risk_avoidance | experience | strategic")
        estimated_annual_benefit: float
        beneficiary: str
        pain_point: str
        initiative_index: int = Field(description="0-based index into initiatives")

    class DemoPortfolio(BaseModel):
        initiatives: TList[DemoInitiative] = Field(description="Exactly 3 strategic initiatives")
        ideas: TList[DemoIdea] = Field(description="Exactly 10 ideas spread across the initiatives")

    if client:
        subject_line = (
            f"Client: {client.strip()}." + (f" Industry: {industry.strip()}." if industry else "")
        )
        grounding = (
            "Research the client's PUBLICLY STATED strategy — annual report themes, "
            "investor communications, announced programs — and anchor every initiative "
            "and idea to what they have actually said they are pursuing. Name the "
            "connection in each initiative's objective."
        )
    else:
        subject_line = f"Industry: {(industry or '').strip()}. No specific client named."
        grounding = (
            "Anchor the initiatives and ideas in the latest major trends currently "
            "reshaping this industry — name the trend each initiative responds to."
        )
    notes_line = f" Presentation focus: {notes}." if notes else ""

    system = (
        "You are a senior innovation consultant preparing a client-tailored portfolio "
        "for a first presentation. Propose exactly 3 strategic initiatives and exactly "
        "10 concrete, credible ideas under them. " + grounding + " Ideas must name a "
        "real beneficiary and pain, carry realistic annual benefit estimates for an "
        "enterprise of this scale, and mix benefit types (not only cost reduction). "
        "Avoid generic digital-transformation filler."
    )
    request = {
        "model": "claude-opus-4-8",
        "max_tokens": 16000,
        "thinking": {"type": "adaptive"},
        "system": system,
        "messages": [{"role": "user", "content": subject_line + notes_line}],
        "output_format": DemoPortfolio,
    }
    anthropic_client = anthropic.Anthropic()
    try:
        # first attempt: with web search so public strategy/trends are current
        response = anthropic_client.messages.parse(
            **request,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        )
        portfolio = response.parsed_output.model_dump()
        portfolio["generated_by"] = "claude+research"
        return portfolio
    except Exception:
        pass
    try:
        # second attempt: model knowledge only (org may not have web search enabled)
        response = anthropic_client.messages.parse(**request)
        portfolio = response.parsed_output.model_dump()
        portfolio["generated_by"] = "claude"
        return portfolio
    except Exception:
        return _template_portfolio(industry, label)
