"""Innovation Hub automation: the engine that removes the manual operations.

Idea triage
    Every submitted idea is matched against the currently detected
    opportunities (token overlap over title/category/description), banded by
    impact, and given a recommendation — fast_track when it lands on a quick
    win, business_case when it lands on bigger/harder work, investigate when
    it matches nothing we can see in the data.

Automation rules (idempotent — safe to run on a schedule or lazily per request)
    auto_observe   Re-runs every metric binding whose source dataset is newer
                   than its latest observation, so verified evidence stays
                   current without anyone clicking "Observe now".
    auto_draft     Creates draft business cases (baseline frozen immediately)
                   for the top unaddressed quick wins above a savings
                   threshold. Humans review and promote; the hub does the
                   paperwork.
    auto_advance   Moves live cases to 'value_realized' once verified evidence
                   reaches the realization threshold vs. forecast.

Every action is written to the automation log so the reduction in manual
operations is itself measurable.
"""
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from . import db, metrics, roi

AUTO_DRAFT_MIN_SAVINGS = 10_000.0   # don't draft paperwork for trivia
AUTO_DRAFT_MAX_PER_RUN = 3
REALIZATION_THRESHOLD = 0.5         # verified >= 50% of forecast -> value_realized
RUN_STALENESS_SECONDS = 900         # lazy trigger: rerun if older than 15 min

BENEFIT_TYPES = ["cost_reduction", "revenue_growth", "risk_avoidance", "experience", "strategic"]

# default horizon by benefit type (overridable at intake): cost plays are core
# (H1), growth/experience are adjacent (H2), strategic bets are transformational (H3)
HORIZON_BY_BENEFIT = {
    "cost_reduction": "h1",
    "risk_avoidance": "h1",
    "revenue_growth": "h2",
    "experience": "h2",
    "strategic": "h3",
}

HORIZON_TARGETS = {"h1": 0.70, "h2": 0.20, "h3": 0.10}  # McKinsey three-horizons mix

DUPLICATE_SIMILARITY = 0.35

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "will",
    "would", "could", "should", "have", "been", "more", "less", "them",
    "then", "than", "when", "what", "where", "which", "their", "there",
    "about", "using", "use", "our", "are", "can", "all", "any", "per",
}


def _tokens(text: str) -> set:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) >= 3 and t not in _STOPWORDS
    }


def _impact_band(savings: float) -> str:
    if savings >= 50_000:
        return "high"
    if savings >= 10_000:
        return "medium"
    return "low"


# -------------------------------------------------- scoring framework config

DEFAULT_SCORING_CONFIG: Dict[str, Any] = {
    # idea scoring: leaders tune these to match evolving priorities
    "idea_weights": {
        "impact": 0.30,          # size of the benefit claim / matched savings
        "data_grounding": 0.20,  # how strongly the idea matches detected signal
        "alignment": 0.15,       # overlap with declared strategic priority themes
        "completeness": 0.10,    # how much of the intake information was provided
        "desirability": 0.25,    # human evidence: who it serves, their pain, peer signal
    },
    "priority_themes": [
        "cost reduction", "automation", "cloud efficiency", "customer experience",
    ],
    "guardrails": {
        "min_annual_benefit": 0,        # 0 disables the floor
        "require_category": False,
        "require_benefit_estimate": False,
    },
    # default opportunity prioritization weights (see prioritization.py)
    "opportunity_weights": {"value": 0.35, "efficiency": 0.30, "speed": 0.15, "simplicity": 0.20},
    # leader-defined criteria: keyword-matched against idea text, weighted into the score
    "custom_criteria": [],
}


class ConfigError(ValueError):
    pass


def get_scoring_config() -> Dict[str, Any]:
    import json
    raw = db.meta_get("scoring_config")
    config = {k: (v.copy() if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
              for k, v in DEFAULT_SCORING_CONFIG.items()}
    if raw:
        stored = json.loads(raw)
        for key in config:
            if key not in stored:
                continue
            if isinstance(config[key], dict) and isinstance(stored[key], dict):
                # merge per-key so configs saved before a new component existed
                # pick up its default weight instead of breaking scoring
                config[key] = {**config[key], **stored[key]}
            else:
                config[key] = stored[key]
    return config


def save_scoring_config(config: Dict[str, Any]) -> Dict[str, Any]:
    import json
    merged = get_scoring_config()
    for key in DEFAULT_SCORING_CONFIG:
        if key in config:
            if isinstance(DEFAULT_SCORING_CONFIG[key], dict) and isinstance(config[key], dict):
                merged[key] = {**merged[key], **config[key]}
            else:
                merged[key] = config[key]
    for weights_key in ("idea_weights", "opportunity_weights"):
        weights = merged[weights_key]
        expected = set(DEFAULT_SCORING_CONFIG[weights_key])
        if set(weights) != expected:
            raise ConfigError(f"{weights_key} must have exactly the keys {sorted(expected)}")
        if any(not isinstance(w, (int, float)) or w < 0 for w in weights.values()):
            raise ConfigError(f"{weights_key} values must be numbers >= 0")
        if sum(weights.values()) <= 0:
            raise ConfigError(f"at least one {weights_key} weight must be > 0")
    if not isinstance(merged["priority_themes"], list):
        raise ConfigError("priority_themes must be a list of strings")
    customs = merged.get("custom_criteria") or []
    if not isinstance(customs, list) or len(customs) > 8:
        raise ConfigError("custom_criteria must be a list (max 8)")
    for c in customs:
        if not (c.get("label") or "").strip():
            raise ConfigError("each custom criterion needs a label")
        if not isinstance(c.get("keywords"), list) or not c["keywords"]:
            raise ConfigError("each custom criterion needs a keywords list")
        if not isinstance(c.get("weight"), (int, float)) or c["weight"] < 0:
            raise ConfigError("custom criterion weight must be a number >= 0")
    db.meta_set("scoring_config", json.dumps(merged))
    return merged


# --------------------------------------------------------------- governance

# access levels, weakest to strongest; each includes everything below it
ROLES = ["contributor", "reviewer", "executive", "admin"]

ROLE_CAPABILITIES = {
    "contributor": "Submit ideas, comment, build on, and vote",
    "reviewer": "Plus: gate decisions on ideas (qualify, prioritize, hold, develop)",
    "executive": "Plus: business-case approvals, rejections, and funding release",
    "admin": "Plus: hub settings — workflow, scoring, roles, governance, demo studio",
}


def check_role(minimum: str, actor: Optional[str]) -> Optional[str]:
    """Profile-based access: open until user profiles exist; once they do,
    every decision-making actor must be registered with sufficient privilege."""
    users = db.list_users()
    if not users:
        return None
    role = db.get_role(actor or "")
    if role is None:
        return f"'{actor or 'anonymous'}' has no user profile — an admin must add one in Hub Settings"
    if ROLES.index(role) < ROLES.index(minimum):
        return f"'{actor}' is a {role}; this action requires {minimum} access or above"
    return None


GOVERNANCE_AREAS = [
    "idea_screening",
    "business_case_approval",
    "delivery",
    "value_verification",
    "portfolio_oversight",
]


def get_governance() -> Dict[str, List[str]]:
    import json
    raw = db.meta_get("governance")
    stored = json.loads(raw) if raw else {}
    return {area: stored.get(area, []) for area in GOVERNANCE_AREAS}


def save_governance(assignments: Dict[str, List[str]]) -> Dict[str, List[str]]:
    import json
    merged = get_governance()
    for area, names in assignments.items():
        if area not in GOVERNANCE_AREAS:
            raise ConfigError(f"unknown governance area '{area}' — expected one of {GOVERNANCE_AREAS}")
        if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
            raise ConfigError("assignments must be lists of names")
        merged[area] = [n.strip() for n in names if n.strip()]
    db.meta_set("governance", json.dumps(merged))
    return merged


def check_authority(area: str, actor: Optional[str]) -> Optional[str]:
    """Returns an error message when governance blocks the action, else None.
    Areas with no assignees are open (governance not yet configured there)."""
    assignees = get_governance().get(area, [])
    if not assignees:
        return None
    if not actor or actor.strip().lower() not in {a.lower() for a in assignees}:
        return (
            f"'{actor or 'anonymous'}' is not assigned to {area.replace('_', ' ')} — "
            f"authorized: {', '.join(assignees)}"
        )
    return None


# ------------------------------------------------------------------ triage

def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def triage_idea(
    title: str,
    description: str,
    opportunities: List[Dict[str, Any]],
    category: Optional[str] = None,
    estimated_annual_benefit: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None,
    benefit_type: Optional[str] = None,
    horizon: Optional[str] = None,
    challenge: Optional[Dict[str, Any]] = None,
    initiative: Optional[Dict[str, Any]] = None,
    existing_ideas: Optional[List[Dict[str, Any]]] = None,
    beneficiary: Optional[str] = None,
    pain_point: Optional[str] = None,
    votes: int = 0,
    build_ons: int = 0,
) -> Dict[str, Any]:
    """Automatic validation, categorization, and prioritization of one idea,
    scored under the (leader-configurable) scoring framework. Enrichment
    performed on incomplete intake is recorded in `enrichment`."""
    config = config or get_scoring_config()
    idea_tokens = _tokens(f"{title} {description}")
    enrichment: List[str] = []

    best: Optional[Tuple[int, Dict[str, Any]]] = None
    for opp in opportunities:
        opp_tokens = _tokens(f"{opp['title']} {opp['category']} {opp['description']}")
        overlap = len(idea_tokens & opp_tokens)
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, opp)

    matched = None
    match_strength = 0
    if best:
        match_strength, opp = best
        matched = {
            "id": opp["id"],
            "title": opp["title"],
            "category": opp["category"],
            "estimated_annual_savings": opp["estimated_annual_savings"],
            "quadrant": opp.get("priority", {}).get("quadrant"),
        }

    # enrichment: fill what intake didn't provide, and say so
    benefit = estimated_annual_benefit
    if benefit is None and matched:
        benefit = matched["estimated_annual_savings"]
        enrichment.append(
            f"No benefit estimate provided — derived {benefit:,.0f}/yr from matched "
            f"opportunity {matched['id']}."
        )
    derived_category = category
    if not derived_category and matched:
        derived_category = matched["category"]
        enrichment.append(f"No category provided — derived '{derived_category}' from matched opportunity.")

    derived_benefit_type = benefit_type
    if not derived_benefit_type:
        derived_benefit_type = "cost_reduction" if matched else "cost_reduction"
        enrichment.append(
            "No benefit type provided — defaulted to 'cost_reduction'"
            + (" (matched a cost opportunity)." if matched else ".")
        )
    derived_horizon = horizon
    if not derived_horizon:
        derived_horizon = HORIZON_BY_BENEFIT.get(derived_benefit_type, "h1")
        enrichment.append(f"Horizon derived as '{derived_horizon}' from benefit type '{derived_benefit_type}'.")

    # duplicate detection against the existing idea backlog
    duplicates = []
    for other in (existing_ideas or []):
        other_tokens = _tokens(f"{other['title']} {other['description']}")
        similarity = _jaccard(idea_tokens, other_tokens)
        if similarity >= DUPLICATE_SIMILARITY:
            duplicates.append({
                "id": other["id"], "title": other["title"],
                "similarity": round(similarity, 2),
            })
    duplicates.sort(key=lambda d: d["similarity"], reverse=True)
    duplicates = duplicates[:3]

    impact_band = _impact_band(benefit) if benefit is not None else "unknown"

    # scoring components (each 0..1)
    impact_score = {"high": 1.0, "medium": 0.6, "low": 0.3, "unknown": 0.15}[impact_band]
    grounding_score = min(match_strength / 6.0, 1.0)
    theme_tokens = set()
    for theme in config["priority_themes"]:
        theme_tokens |= _tokens(theme)
    alignment_score = 1.0 if idea_tokens & theme_tokens else 0.0
    if challenge and challenge.get("status") == "active":
        alignment_score = 1.0  # answering a leadership challenge is aligned by definition
    if initiative:
        alignment_score = 1.0  # tagged to a declared strategic initiative
    provided = [
        bool(category), estimated_annual_benefit is not None, len(description) >= 80,
    ]
    completeness_score = sum(provided) / len(provided)

    # desirability: does a human need anchor this idea, and do peers recognize it?
    social_signal = min((votes + 2 * build_ons) / 5.0, 1.0)
    desirability_score = round(
        0.4 * (1.0 if (beneficiary or "").strip() else 0.0)
        + 0.4 * (1.0 if (pain_point or "").strip() else 0.0)
        + 0.2 * social_signal, 3,
    )
    if not (beneficiary or "").strip():
        enrichment.append("No beneficiary named — who is this for?")
    if not (pain_point or "").strip():
        enrichment.append("No pain point described — what human problem does this solve?")

    weights = config["idea_weights"]
    customs = config.get("custom_criteria") or []
    custom_components = {}
    custom_weighted = 0.0
    for criterion in customs:
        kw_tokens = set()
        for kw in criterion["keywords"]:
            kw_tokens |= _tokens(str(kw))
        hit = 1.0 if idea_tokens & kw_tokens else 0.0
        custom_components[f"custom: {criterion['label']}"] = hit
        custom_weighted += criterion["weight"] * hit
    total_weight = (sum(weights.values()) + sum(c["weight"] for c in customs)) or 1.0
    score = round(100 * (
        weights["impact"] * impact_score
        + weights["data_grounding"] * grounding_score
        + weights["alignment"] * alignment_score
        + weights["completeness"] * completeness_score
        + weights.get("desirability", 0) * desirability_score
        + custom_weighted
    ) / total_weight, 1)

    # guardrails: leaders' hard constraints, flagged not silently dropped
    guardrails = config["guardrails"]
    flags: List[str] = []
    min_benefit = guardrails.get("min_annual_benefit") or 0
    if min_benefit > 0 and (benefit or 0) < min_benefit:
        flags.append(f"Below the ${min_benefit:,.0f}/yr minimum benefit guardrail.")
    if guardrails.get("require_category") and not category:
        flags.append("Category is required by the intake guardrails but was not provided.")
    if guardrails.get("require_benefit_estimate") and estimated_annual_benefit is None:
        flags.append("A benefit estimate is required by the intake guardrails but was not provided.")

    if matched:
        recommendation = (
            "fast_track" if matched["quadrant"] == "quick_win" else "business_case"
        )
        rationale = (
            f"Matches detected opportunity '{matched['title']}' "
            f"(${matched['estimated_annual_savings']:,.0f}/yr, {matched['quadrant'] or 'unscored'}). "
            + ("Quick win — fast-track to approval." if recommendation == "fast_track"
               else "Sizeable but non-trivial — develop the business case.")
        )
    else:
        recommendation = "investigate"
        rationale = (
            "No matching signal in the loaded data sources — needs discovery "
            "before a value case can be anchored."
        )
    if flags:
        recommendation = "needs_info"
        rationale += " Intake guardrails are not met — see flags."

    if duplicates:
        enrichment.append(
            "Possible duplicate of: "
            + ", ".join(f"{d['id']} ({d['similarity']:.0%} similar)" for d in duplicates)
        )

    return {
        "matched_opportunity": matched,
        "match_strength": match_strength,
        "impact_band": impact_band,
        "benefit_type": derived_benefit_type,
        "horizon": derived_horizon,
        "possible_duplicates": duplicates,
        "challenge_id": (challenge or {}).get("id"),
        "score": score,
        "score_components": {
            "impact": round(impact_score, 2),
            "data_grounding": round(grounding_score, 2),
            "alignment": round(alignment_score, 2),
            "completeness": round(completeness_score, 2),
            "desirability": round(desirability_score, 2),
            **{k: round(v, 2) for k, v in custom_components.items()},
        },
        "derived_category": derived_category,
        "estimated_annual_benefit": benefit,
        "guardrail_flags": flags,
        "enrichment": enrichment,
        "recommendation": recommendation,
        "rationale": rationale,
    }


# ------------------------------------------------------------ AI evaluation

_DOMAIN_DRAFTS = [
    (("cloud", "vm", "instance", "server", "infrastructure", "compute"),
     "cloud infrastructure runs over-provisioned and partly idle, so spend grows faster than usage",
     "the platform and finance teams", "reduce run-rate cloud spend within two quarters"),
    (("license", "licenses", "software", "subscription", "tool", "tools"),
     "overlapping tools and unused licenses accumulate quietly across teams",
     "IT asset management and every budget owner", "cut software spend without losing capability"),
    (("ticket", "support", "helpdesk", "service desk", "reset", "password"),
     "high-volume, repetitive requests crowd the service desk and keep users waiting",
     "service-desk agents and every employee who raises a ticket",
     "deflect routine requests to self-service and cut resolution time"),
    (("invoice", "payment", "procurement", "vendor", "finance", "expense"),
     "finance staff manually reconcile and chase transactions that software could match",
     "the finance operations team and suppliers awaiting payment",
     "shrink manual exception handling and pay suppliers on time"),
    (("onboarding", "hr", "employee", "provisioning", "training"),
     "new joiners wait days for accounts, hardware, and access provisioned by checklist",
     "new employees and the teams waiting for them to be productive",
     "cut time-to-productive from days to hours"),
    (("report", "reporting", "dashboard", "analytics", "data"),
     "teams assemble reports by hand from scattered sources, so decisions wait on stale numbers",
     "managers who decide with the numbers, and the analysts who compile them",
     "give decision-makers live, trusted numbers without manual assembly"),
    (("automate", "automation", "manual", "process", "workflow", "rpa"),
     "a repetitive manual process consumes skilled people's time and introduces errors",
     "the team performing the work today", "free capacity and remove rework"),
]


def _template_draft(title: str, opportunities: Optional[List[Dict[str, Any]]]) -> str:
    """Compose a complete draft from what the hub already knows: the matched
    opportunity from the customer's own data when one exists, otherwise a
    domain template chosen by the title's subject matter."""
    idea_tokens = _tokens(title)
    best = None
    for opp in opportunities or []:
        overlap = len(idea_tokens & _tokens(f"{opp['title']} {opp['category']} {opp['description']}"))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, opp)
    if best:
        opp = best[1]
        return (
            f"Problem today: {opp['description'].rstrip('.')} — detected in our own data, "
            f"affecting {opp.get('affected_count', 'multiple')} items. "
            f"Proposed change: {title.rstrip('.')}. "
            f"Who benefits: the teams behind '{opp['category']}' operations. "
            f"Expected outcome: approximately ${opp['estimated_annual_savings']:,.0f}/yr, "
            f"based on the matched opportunity ({opp['id']})."
        )
    low = title.lower()
    for keywords, problem, who, outcome in _DOMAIN_DRAFTS:
        if any(k in low for k in keywords):
            return (f"Problem today: {problem}. "
                    f"Proposed change: {title.rstrip('.')}. "
                    f"Who benefits: {who}. "
                    f"Expected outcome: {outcome}; we will quantify the annual value "
                    "against a measured baseline before approval.")
    return (f"Problem today: the work this addresses is done manually or not at all, "
            f"and its cost is invisible until measured. "
            f"Proposed change: {title.rstrip('.')}. "
            f"Who benefits: the team closest to this work — name them before submitting. "
            f"Expected outcome: a measurable reduction in time or cost; add a rough "
            "annual estimate so triage can prioritize it.")


def assist_idea_description(title: str, description: str = "",
                            opportunities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Draft a description from the title, or review a submitter's own text and
    recommend improvements. Template mode never invents facts: it returns a
    fill-in scaffold or suggestions only, clearly labeled."""
    import os

    mode = "improve" if description.strip() else "generate"

    def _heuristic_suggestions(text: str) -> List[str]:
        low = text.lower()
        out = []
        if len(text) < 80:
            out.append("Expand the description — reviewers score short submissions lower "
                       "because they can't judge feasibility or value.")
        if not any(w in low for w in ("today", "currently", "manual", "problem", "pain", "slow", "error")):
            out.append("Describe the situation today: what is broken, slow, or manual right now?")
        if not any(w in low for w in ("customer", "team", "agent", "employee", "user", "analyst", "engineer")):
            out.append("Name who benefits — ideas anchored to a specific beneficiary score "
                       "higher on desirability.")
        if not any(ch.isdigit() for ch in text) and "$" not in text and "%" not in text:
            out.append("Add a number, even a rough one: hours per week, tickets per month, "
                       "or an annual dollar estimate.")
        if not any(w in low for w in ("reduce", "save", "cut", "increase", "improve",
                                      "eliminate", "automate", "faster", "avoid")):
            out.append("State the expected change as a measurable outcome "
                       "(e.g. 'cut resolution time by half').")
        return out

    if not os.environ.get("ANTHROPIC_API_KEY"):
        if mode == "generate":
            return {"mode": mode, "draft": _template_draft(title, opportunities),
                    "generated_by": "template",
                    "suggestions": ["Drafted from the hub's detected-opportunity data and "
                                    "domain templates — verify the specifics and adjust "
                                    "numbers before submitting."]}
        return {"mode": mode, "draft": description, "generated_by": "template",
                "suggestions": _heuristic_suggestions(description)
                or ["Reads well — covers the problem, beneficiary, and a measurable outcome."]}

    import anthropic
    from pydantic import BaseModel, Field
    from typing import List as TList

    class DescriptionAssist(BaseModel):
        draft: str = Field(description="The drafted or improved description, 3-5 sentences, "
                                       "covering problem today, proposed change, who benefits, "
                                       "and expected measurable outcome")
        suggestions: TList[str] = Field(description="Specific things the submitter should add, "
                                                    "verify, or quantify; empty if none")

    client = anthropic.Anthropic()
    try:
        if mode == "generate":
            task = (f"Idea title: {title}\n\nDraft a submission description for this idea. "
                    "Where a fact is unknowable from the title (numbers, team names), use an "
                    "explicit <placeholder> the submitter must fill in — never invent specifics.")
        else:
            task = (f"Idea title: {title}\nSubmitter's description: {description}\n\n"
                    "Improve this description: keep every fact the submitter stated, tighten "
                    "the wording, and structure it as problem / change / beneficiary / outcome. "
                    "List what is still missing or unquantified as suggestions.")
        response = client.messages.parse(
            model="claude-opus-4-8",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=("You help employees write clear innovation-idea submissions. Preserve "
                    "their facts exactly; never fabricate numbers or specifics — use "
                    "<placeholders> for anything unknown."),
            messages=[{"role": "user", "content": task}],
            output_format=DescriptionAssist,
        )
        result = response.parsed_output.model_dump()
        return {"mode": mode, "generated_by": "claude", **result}
    except Exception as exc:
        base = {"mode": mode, "generated_by": "template",
                "suggestions": [f"AI assist unavailable ({type(exc).__name__}); "
                                "heuristic guidance shown instead."]}
        if mode == "improve":
            base["draft"] = description
            base["suggestions"] += _heuristic_suggestions(description)
        else:
            base["draft"] = _template_draft(title, opportunities)
        return base


def red_team_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Adversarial pre-mortem for a business case. Template mode challenges the
    plan's own assumptions; AI mode prosecutes properly."""
    import os
    plan = case.get("roi_plan") or {}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        modes = [f"Assumption may not hold: {a}" for a in plan.get("assumptions", [])[:3]]
        modes += [f"Measurement risk: {r}" for r in plan.get("measurement_risks", [])[:2]]
        if plan.get("unmeasurable_claims"):
            modes.append("Parts of the claimed value cannot be verified from any named data source")
        return {
            "killer_assumption": (plan.get("assumptions") or ["Benefits materialize as claimed"])[0],
            "failure_modes": modes or ["Benefits assumed rather than measured"],
            "hidden_costs": ["Change management and adoption effort",
                             "Integration and data-quality remediation",
                             "Ongoing run cost after go-live"],
            "cannibalization": "Check whether this displaces value already counted by "
                               "another initiative.",
            "recommendation": "Fund a tranche gated on retiring the killer assumption "
                              "before full commitment.",
            "generated_by": "template",
        }
    import anthropic
    from pydantic import BaseModel, Field
    from typing import List as TList

    class RedTeamMemo(BaseModel):
        killer_assumption: str = Field(description="The single assumption most likely to sink this")
        failure_modes: TList[str]
        hidden_costs: TList[str]
        cannibalization: str = Field(description="What existing value this might displace")
        recommendation: str = Field(description="What the committee should demand before funding")

    client = anthropic.Anthropic()
    try:
        r = client.messages.parse(
            model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
            system=("You are the red team in an investment committee. Prosecute this "
                    "business case: find the killer assumption, realistic failure modes, "
                    "hidden costs, and cannibalization. Be specific and unsparing but fair."),
            messages=[{"role": "user", "content":
                       f"Title: {case['title']}\nDescription: {case['description']}\n"
                       f"Plan summary: {plan.get('summary', '')}\n"
                       f"Assumptions: {plan.get('assumptions', [])}\n"
                       f"KPIs: {[k['name'] for k in plan.get('kpis', [])]}"}],
            output_format=RedTeamMemo)
        memo = r.parsed_output.model_dump()
        memo["generated_by"] = "claude"
        return memo
    except Exception:
        case2 = dict(case)
        os_key = None
        return red_team_case({**case2, "roi_plan": plan}) if False else {
            "killer_assumption": (plan.get("assumptions") or ["Benefits materialize as claimed"])[0],
            "failure_modes": ["AI red team unavailable; template challenge applied"] +
                             [f"Assumption may not hold: {a}" for a in plan.get("assumptions", [])[:3]],
            "hidden_costs": ["Change management", "Integration effort", "Run cost"],
            "cannibalization": "Unassessed — verify against adjacent initiatives.",
            "recommendation": "Gate funding on retiring the top assumption.",
            "generated_by": "template",
        }


_RADAR_TEMPLATES = {
    "default": [
        "Industry majors are consolidating around AI-assisted operations",
        "Cost-of-capital pressure is shifting budgets from growth to efficiency",
        "Regulators are increasing scrutiny of automated decision-making",
    ],
}


def radar_scan(topic: str) -> Dict[str, Any]:
    """Research a competitor/trend and draft a response challenge with starter
    ideas. Web-grounded with a key; honest template signals without."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "signals": [f"{sig} (template signal — no research key configured)"
                        for sig in _RADAR_TEMPLATES["default"]],
            "challenge_title": f"Respond to: {topic}",
            "challenge_question": (f"'{topic}' is moving — where can we respond within one "
                                   "quarter with measurable value? Ideas with a named "
                                   "beneficiary and a number get fast-tracked."),
            "theme": "competitive-response",
            "starter_ideas": [
                f"Map our capability gaps against {topic} and rank by time-to-close",
                f"Identify which of our detected opportunities blunt {topic}'s advantage",
                f"Run a one-week customer-impact probe on {topic}",
            ],
            "generated_by": "template",
        }
    import anthropic
    from pydantic import BaseModel, Field
    from typing import List as TList

    class RadarDraft(BaseModel):
        signals: TList[str] = Field(description="3 concrete, recent, sourced signals")
        challenge_title: str
        challenge_question: str
        theme: str
        starter_ideas: TList[str] = Field(description="3 starter ideas, each with a measurable angle")

    client = anthropic.Anthropic()
    try:
        r = client.messages.parse(
            model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
            system=("You scan market signals for an innovation program. Research the topic "
                    "with web search, extract three concrete recent signals, and draft a "
                    "focused innovation challenge with three starter ideas."),
            messages=[{"role": "user", "content": f"Topic to scan: {topic}"}],
            output_format=RadarDraft)
        draft = r.parsed_output.model_dump()
        draft["generated_by"] = "claude"
        return draft
    except Exception:
        out = radar_scan.__wrapped__(topic) if hasattr(radar_scan, "__wrapped__") else None
        return {
            "signals": [f"{sig} (AI research unavailable; template signal)"
                        for sig in _RADAR_TEMPLATES["default"]],
            "challenge_title": f"Respond to: {topic}",
            "challenge_question": f"'{topic}' is moving — where can we respond within one quarter?",
            "theme": "competitive-response",
            "starter_ideas": [f"Map capability gaps against {topic}"],
            "generated_by": "template",
        }


def ai_evaluate_idea(idea: Dict[str, Any],
                     opportunities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deeper AI validation of one idea: measurability check, categorization,
    missing intake information, duplicate risk. Falls back to a deterministic
    assessment when no API key is configured."""
    import os

    heuristic = (idea.get("assessment") or {})
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "validated": bool(heuristic.get("matched_opportunity")),
            "validation_notes": (
                "Template evaluation (no ANTHROPIC_API_KEY): validation is based on "
                "whether the idea matches a detected opportunity."
            ),
            "category": idea.get("category") or heuristic.get("derived_category") or "uncategorized",
            "missing_information": list(heuristic.get("guardrail_flags", [])),
            "suggested_priority": heuristic.get("recommendation", "investigate"),
            "duplicate_risk": "unknown",
            "generated_by": "template",
        }

    import anthropic
    from pydantic import BaseModel, Field
    from typing import List as TList

    class IdeaEvaluation(BaseModel):
        validated: bool = Field(description="Is the value claim plausible and measurable from typical enterprise data?")
        validation_notes: str
        category: str = Field(description="Best-fit category, e.g. 'service automation', 'cloud efficiency'")
        missing_information: TList[str] = Field(description="Intake details still needed to evaluate this properly")
        suggested_priority: str = Field(description="'fast_track', 'business_case', 'investigate', or 'reject'")
        duplicate_risk: str = Field(description="'high'/'medium'/'low' with respect to the listed opportunities and why")

    opp_lines = "\n".join(
        f"- {o['id']}: {o['title']} (${o['estimated_annual_savings']:,.0f}/yr, {o['category']})"
        for o in opportunities[:15]
    )
    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model="claude-opus-4-8",
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=(
                "You are the intake evaluator for an innovation hub. Validate ideas "
                "quickly and consistently: is the claimed value measurable from typical "
                "enterprise systems, what category does it belong to, what intake "
                "information is missing, and how should it be prioritized. Be direct "
                "and consistent; do not inflate weak ideas."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Idea title: {idea['title']}\n"
                    f"Description: {idea['description']}\n"
                    f"Category given: {idea.get('category') or '(none)'}\n"
                    f"Benefit estimate given: {idea.get('estimated_annual_benefit') or '(none)'}\n\n"
                    f"Opportunities already detected from this customer's data:\n{opp_lines}\n\n"
                    "Evaluate this idea."
                ),
            }],
            output_format=IdeaEvaluation,
        )
        evaluation = response.parsed_output.model_dump()
        evaluation["generated_by"] = "claude"
        return evaluation
    except Exception as exc:
        return {
            "validated": bool(heuristic.get("matched_opportunity")),
            "validation_notes": f"AI evaluation failed ({type(exc).__name__}); heuristic result kept.",
            "category": idea.get("category") or heuristic.get("derived_category") or "uncategorized",
            "missing_information": list(heuristic.get("guardrail_flags", [])),
            "suggested_priority": heuristic.get("recommendation", "investigate"),
            "duplicate_risk": "unknown",
            "generated_by": "template",
        }


# -------------------------------------------------------------- automation

def _auto_observe(cases: List[Dict[str, Any]],
                  datasets: Dict[str, List[Dict[str, Any]]],
                  dataset_meta: Dict[str, Dict[str, Any]]) -> int:
    refreshed = 0
    for case in cases:
        for binding in case["metric_bindings"]:
            source = binding["definition"].get("source")
            source_updated = (dataset_meta.get(source) or {}).get("updated_at")
            if not source_updated:
                continue
            last_observed = (
                binding["observations"][-1]["observed_at"]
                if binding["observations"] else binding["baseline_captured_at"]
            )
            if source_updated <= last_observed:
                continue  # nothing new to measure
            observation = metrics.compute(binding["definition"], datasets)
            db.add_metric_observation(
                case["id"], binding["id"], observation["value"], observation["rows_matched"]
            )
            db.log_automation(
                "auto_observe", "observed", case["id"],
                f"{binding['label']}: {observation['value']:,.2f} "
                f"(source '{source}' updated {source_updated[:10]})",
            )
            refreshed += 1
    return refreshed


def _auto_draft(opportunities: List[Dict[str, Any]],
                cases: List[Dict[str, Any]],
                datasets: Dict[str, List[Dict[str, Any]]]) -> int:
    linked = {(c["linked_opportunity"] or {}).get("id") for c in cases}
    drafted = 0
    for opp in opportunities:
        if drafted >= AUTO_DRAFT_MAX_PER_RUN:
            break
        if (
            opp["id"] in linked
            or opp["priority"]["quadrant"] != "quick_win"
            or opp["estimated_annual_savings"] < AUTO_DRAFT_MIN_SAVINGS
        ):
            continue
        # Template plan on purpose: drafting must be fast, free, and
        # deterministic. Reviewers regenerate with AI when they pick it up.
        plan = roi._template_plan(
            opp["title"], opp["description"], opp["priority"]["est_implementation_cost"]
        )
        snapshot = {
            k: opp[k]
            for k in ("id", "title", "category", "source",
                      "estimated_annual_savings", "description")
        }
        case = db.create_business_case(
            title=f"[Auto-draft] {opp['title']}",
            description=(
                f"Drafted by the hub from detected opportunity {opp['id']}. "
                f"{opp['description']}"
            ),
            estimated_cost=opp["priority"]["est_implementation_cost"],
            roi_plan=plan.model_dump(),
            generated_by="automation",
            note="Auto-drafted — review, adjust cost, and promote to proposed.",
            linked_opportunity=snapshot,
            stage="draft",
        )
        measure = opp.get("measure")
        if measure:
            definition = {k: v for k, v in measure.items() if k != "label"}
            baseline = metrics.compute(definition, datasets)
            db.create_metric_binding(
                case_id=case["id"], label=measure["label"], kpi_name=None,
                definition=definition, unit=metrics.unit_for(definition),
                baseline_value=baseline["value"], baseline_rows=baseline["rows_matched"],
            )
        db.log_automation(
            "auto_draft", "drafted", case["id"],
            f"{opp['title']} — ${opp['estimated_annual_savings']:,.0f}/yr quick win, "
            "baseline frozen",
        )
        drafted += 1
    return drafted


def _auto_advance(cases: List[Dict[str, Any]]) -> int:
    advanced = 0
    for case in cases:
        if case["stage"] != "live":
            continue
        forecast = (case["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
        measured = (case["tracking"] or {}).get("measured_annual_savings") or 0
        if forecast > 0 and measured >= forecast * REALIZATION_THRESHOLD:
            db.set_stage(case["id"], "value_realized")
            db.log_automation(
                "auto_advance", "value_realized", case["id"],
                f"verified ${measured:,.0f}/yr >= {REALIZATION_THRESHOLD:.0%} of "
                f"${forecast:,.0f}/yr forecast",
            )
            advanced += 1
    return advanced


def run_automation(
    opportunities: List[Dict[str, Any]],
    datasets: Dict[str, List[Dict[str, Any]]],
    dataset_meta: Dict[str, Dict[str, Any]],
) -> Dict[str, int]:
    cases = db.list_business_cases()
    summary = {
        "observed": _auto_observe(cases, datasets, dataset_meta),
        "drafted": _auto_draft(opportunities, cases, datasets),
        # re-read: auto_observe may have produced the evidence auto_advance needs
        "advanced": _auto_advance(db.list_business_cases()),
    }
    db.meta_set("automation_last_run", datetime.datetime.now(datetime.timezone.utc).isoformat())
    return summary


def automation_is_stale() -> bool:
    last = db.meta_get("automation_last_run")
    if not last:
        return True
    try:
        last_dt = datetime.datetime.fromisoformat(last)
    except ValueError:
        return True
    age = datetime.datetime.now(datetime.timezone.utc) - last_dt
    return age.total_seconds() > RUN_STALENESS_SECONDS


# ------------------------------------------------------------- hub metrics

def _days_between(a: str, b: str) -> Optional[float]:
    try:
        start = datetime.datetime.fromisoformat(a.replace("Z", "+00:00"))
        end = datetime.datetime.fromisoformat(b.replace("Z", "+00:00"))
        return max((end - start).total_seconds() / 86400, 0)
    except ValueError:
        return None


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def hub_metrics(cases: List[Dict[str, Any]], ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    pipeline = {stage: 0 for stage in db.STAGES}
    for case in cases:
        pipeline[case.get("stage") or "proposed"] = pipeline.get(case.get("stage") or "proposed", 0) + 1

    to_live: List[float] = []
    to_evidence: List[float] = []
    for case in cases:
        stages = {h["stage"]: h["entered_at"] for h in case.get("stage_history", [])}
        created = case["submitted_at"]
        if "live" in stages:
            d = _days_between(created, stages["live"])
            if d is not None:
                to_live.append(d)
            first_evidence = next(
                (o["observed_at"] for b in case["metric_bindings"]
                 for o in b["observations"]), None,
            )
            if first_evidence:
                d = _days_between(stages["live"], first_evidence)
                if d is not None:
                    to_evidence.append(d)

    idea_counts: Dict[str, int] = {}
    for idea in ideas:
        idea_counts[idea["status"]] = idea_counts.get(idea["status"], 0) + 1

    horizon_mix: Dict[str, Dict[str, float]] = {
        h: {"count": 0, "value": 0.0} for h in ("h1", "h2", "h3")
    }
    active_cases = [c for c in cases if c.get("stage") != "closed"]
    for case in active_cases:
        h = case.get("horizon") or "h1"
        forecast = (case["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
        horizon_mix.setdefault(h, {"count": 0, "value": 0.0})
        horizon_mix[h]["count"] += 1
        horizon_mix[h]["value"] += forecast
    total_hval = sum(b["value"] for b in horizon_mix.values()) or 0
    for h, bucket in horizon_mix.items():
        bucket["value"] = round(bucket["value"], 2)
        bucket["share"] = round(bucket["value"] / total_hval, 3) if total_hval else None
        bucket["target_share"] = HORIZON_TARGETS.get(h)

    promoted = sum(1 for i in ideas if i["status"] == "business_case")
    recent = db.automation_log_entries(limit=8)
    action_counts: Dict[str, int] = {}
    for entry in db.automation_log_entries(limit=500):
        action_counts[entry["rule"]] = action_counts.get(entry["rule"], 0) + 1

    return {
        "pipeline_stages": pipeline,
        "time_to_value": {
            "median_days_to_live": _median(to_live),
            "median_days_live_to_evidence": _median(to_evidence),
        },
        "ideas": {
            "total": len(ideas),
            "by_status": idea_counts,
            "conversion_rate": round(promoted / len(ideas), 2) if ideas else None,
        },
        "experiments": db.experiment_stats(),
        "horizon_mix": horizon_mix,
        "automation": {
            "last_run": db.meta_get("automation_last_run"),
            "actions_by_rule": action_counts,
            "recent": recent,
        },
    }


# ------------------------------------------------------- idea-to-portfolio gates

# Formal stage-gate lifecycle (modeled on enterprise portfolio stage-gate
# processes): ideas advance through named gates with declared criteria and a
# responsible governance forum. Terminal exits: declined, backlog (hold).
DEFAULT_WORKFLOW = [
    {"key": "proposed", "label": "Proposed", "gate": "Qualification (GO/NO-GO)",
     "forum": "idea_screening",
     "purpose": "Validate the idea is sponsored, novel, and strategically aligned "
                "before spending discovery effort.",
     "criteria": ["Named business sponsor", "No existing solution / not a duplicate",
                  "Strategic alignment", "Intake guardrails met"]},
    {"key": "qualified", "label": "Qualified", "gate": "Prioritization (portfolio register)",
     "forum": "portfolio_oversight",
     "purpose": "Rank qualified ideas by business impact against capability and capacity.",
     "criteria": ["Business impact", "Capability (data grounding)", "Capacity"]},
    {"key": "prioritized", "label": "Prioritized", "gate": "AI-developed business case",
     "forum": "portfolio_oversight",
     "purpose": "The hub develops the business case with AI, ready for executive review.",
     "criteria": ["AI ROI plan with KPIs and baselines", "Evidence baseline frozen where matched"]},
]


def get_workflow() -> List[Dict[str, Any]]:
    import json
    raw = db.meta_get("workflow_steps")
    if raw:
        return json.loads(raw)
    return [dict(s, criteria=list(s["criteria"])) for s in DEFAULT_WORKFLOW]


def save_workflow(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    import json, re
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ConfigError("workflow must have 1-8 steps")
    cleaned = []
    keys = set()
    for i, s in enumerate(steps):
        key = (s.get("key") or "").strip().lower()
        if i == 0:
            key = "proposed"  # intake is fixed: every idea enters here
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", key):
            raise ConfigError(f"invalid step key '{key}' (lowercase slug)")
        if key in keys or key in ("business_case", "backlog", "declined"):
            raise ConfigError(f"duplicate or reserved step key '{key}'")
        keys.add(key)
        forum = s.get("forum") or "idea_screening"
        if forum not in GOVERNANCE_AREAS:
            raise ConfigError(f"forum must be one of {GOVERNANCE_AREAS}")
        criteria = s.get("criteria") or []
        if not isinstance(criteria, list) or any(not isinstance(c, str) for c in criteria):
            raise ConfigError("criteria must be a list of strings")
        cleaned.append({
            "key": key,
            "label": (s.get("label") or key.title()).strip()[:40],
            "gate": (s.get("gate") or "Gate").strip()[:80],
            "forum": forum,
            "purpose": (s.get("purpose") or "").strip()[:400],
            "criteria": [c.strip()[:120] for c in criteria if c.strip()],
        })
    db.meta_set("workflow_steps", json.dumps(cleaned))
    return cleaned


def workflow_keys() -> List[str]:
    return [s["key"] for s in get_workflow()]


def IDEA_STAGES_DYNAMIC() -> List[str]:
    return workflow_keys() + ["business_case"]


IDEA_STAGES = ["proposed", "qualified", "prioritized", "business_case"]  # default snapshot

def lifecycle_spec() -> List[Dict[str, Any]]:
    steps = get_workflow()
    spec = []
    for i, s in enumerate(steps):
        spec.append({
            "stage": s["key"],
            "step": f"Step {i + 1} — {s['label']}",
            "gate": s["gate"],
            "forum": s["forum"],
            "purpose": s["purpose"],
            "criteria": s["criteria"],
            "decisions": (["develop", "hold", "feedback"] if i == len(steps) - 1
                          else ["advance", "hold", "reject", "feedback"] if i > 0
                          else ["advance", "reject", "feedback"]),
        })
    spec.append(_BUSINESS_CASE_SPEC)
    return spec


_BUSINESS_CASE_SPEC = {
    "stage": "business_case",
    "step": "Executive review, funding, delivery",
    "gate": "Business case approved → funded → mobilized",
    "forum": "business_case_approval",
    "purpose": "Executives review business value, opportunity cost, and ROI; approval "
               "unlocks funding, and a released tranche is required to mobilize.",
    "criteria": ["Business value and ROI reviewed", "Funding tranche released before mobilization",
                 "Value verified against the frozen baseline after go-live"],
    "decisions": [],
}

_LEGACY_LIFECYCLE_SPEC = [
    {
        "stage": "proposed",
        "step": "Step 1 — Intake & qualification",
        "gate": "Qualification (GO/NO-GO)",
        "forum": "idea_screening",
        "purpose": "Validate the idea is sponsored, novel, and strategically aligned "
                   "before spending discovery effort.",
        "criteria": [
            "Named business sponsor",
            "No existing solution / not a duplicate",
            "Strategic alignment (theme, challenge, or initiative)",
            "Intake guardrails met",
        ],
        "decisions": ["qualify", "reject", "feedback"],
    },
    {
        "stage": "qualified",
        "step": "Step 2 — Portfolio prioritization",
        "gate": "Prioritization (portfolio register)",
        "forum": "portfolio_oversight",
        "purpose": "Rank qualified ideas by business impact against capability and "
                   "capacity; only prioritized ideas earn a business case.",
        "criteria": [
            "Business impact (benefit estimate / matched savings)",
            "Capability (grounding in detected data signal)",
            "Capacity (portfolio balance and load)",
        ],
        "decisions": ["prioritize", "hold", "reject", "feedback"],
    },
    {
        "stage": "prioritized",
        "step": "Step 3 — Business case development",
        "gate": "AI-developed business case",
        "forum": "portfolio_oversight",
        "purpose": "The hub develops the business case with AI — ROI plan, KPIs, "
                   "frozen evidence baseline — ready for executive review.",
        "criteria": [
            "AI ROI plan with KPIs, baselines, and measurement design",
            "Evidence baseline frozen from source data where matched",
        ],
        "decisions": ["develop", "hold", "feedback"],
    },
    {
        "stage": "business_case",
        "step": "Steps 4-5 — Executive review, funding, delivery",
        "gate": "Business case approved → funded → mobilized",
        "forum": "business_case_approval",
        "purpose": "Executives review business value, opportunity cost, and ROI; "
                   "approval unlocks funding, and a released tranche is required to "
                   "mobilize into delivery.",
        "criteria": [
            "Business value and ROI reviewed",
            "Funding tranche released before mobilization",
            "Value verified against the frozen baseline after go-live",
        ],
        "decisions": [],
    },
]


def gate_checklist(idea: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The qualification-gate checks, computed from what triage already knows —
    shown to the screening forum so decisions are consistent and fast."""
    assessment = idea.get("assessment") or {}
    checks = [
        ("Named business sponsor", bool(idea.get("submitter"))),
        ("No existing solution / duplicate", not assessment.get("possible_duplicates")),
        ("Strategic alignment", (assessment.get("score_components") or {}).get("alignment", 0) > 0
         or bool(idea.get("initiative_ids")) or bool(idea.get("challenge_id"))),
        ("Intake guardrails met", not assessment.get("guardrail_flags")),
    ]
    return [{"check": name, "passed": passed} for name, passed in checks]


# ------------------------------------------------------------- pipeline analytics

def _pipeline_phases():
    return [
        ("A. Ideas-to-portfolio", "idea", workflow_keys()),
        ("B. Portfolio-to-business-case", "case", ["draft", "proposed", "experiment", "approved"]),
        ("C. Delivery & value", "case", ["in_delivery", "live", "value_realized", "scale"]),
    ]


PIPELINE_PHASES = [
    ("A. Ideas-to-portfolio", "idea", ["proposed", "qualified", "prioritized"]),
    ("B. Portfolio-to-business-case", "case", ["draft", "proposed", "experiment", "approved"]),
    ("C. Delivery & value", "case", ["in_delivery", "live", "value_realized", "scale"]),
]

_IDEA_ORDER = ["proposed", "qualified", "prioritized"]
_AGING_DAYS = 14


def _days_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        then = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if then.tzinfo is None:
            then = then.replace(tzinfo=datetime.timezone.utc)
        return round((datetime.datetime.now(datetime.timezone.utc) - then).total_seconds() / 86400, 1)
    except ValueError:
        return None


def build_pipeline(ideas: List[Dict[str, Any]], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Flow analytics across the full lifecycle: per-stage items, value,
    gate conversion (share of entrants that pass), and median dwell."""
    transitions = db.idea_transitions()
    by_idea: Dict[str, Dict[str, str]] = {}
    for t in transitions:
        by_idea.setdefault(t["subject_id"], {})[t["action"]] = t["created_at"]

    def idea_value(i: Dict[str, Any]) -> float:
        return (i.get("estimated_annual_benefit")
                or (i.get("assessment") or {}).get("estimated_annual_benefit") or 0)

    # entered-at for an idea's *current* stage
    def idea_entered(i: Dict[str, Any]) -> Optional[str]:
        events = by_idea.get(i["id"], {})
        return {
            "proposed": i["submitted_at"],
            "qualified": events.get("qualify"),
            "prioritized": events.get("prioritize"),
        }.get(i["status"]) or i["submitted_at"]

    # dwell medians for completed idea transitions
    def _completed_dwells(stage: str) -> List[float]:
        out = []
        for i in ideas:
            events = by_idea.get(i["id"], {})
            start, end = {
                "proposed": (i["submitted_at"], events.get("qualify")),
                "qualified": (events.get("qualify"), events.get("prioritize")),
                "prioritized": (events.get("prioritize"), events.get("develop")),
            }.get(stage, (None, None))
            if start and end:
                d = _days_between(start, end)
                if d is not None:
                    out.append(d)
        return out

    case_history: Dict[str, List[Dict[str, str]]] = {
        c["id"]: c.get("stage_history", []) for c in cases
    }

    def case_reached(stage: str) -> int:
        return sum(1 for c in cases
                   if c["stage"] == stage or any(h["stage"] == stage for h in case_history[c["id"]]))

    def case_dwells(stage: str) -> List[float]:
        out = []
        for c in cases:
            history = case_history[c["id"]]
            for idx, h in enumerate(history):
                if h["stage"] == stage and idx + 1 < len(history):
                    d = _days_between(h["entered_at"], history[idx + 1]["entered_at"])
                    if d is not None:
                        out.append(d)
        return out

    def case_entered(c: Dict[str, Any]) -> Optional[str]:
        for h in reversed(c.get("stage_history", [])):
            if h["stage"] == c["stage"]:
                return h["entered_at"]
        return c["submitted_at"]

    keys = workflow_keys()
    reached_idea = {k: 0 for k in keys}
    for i in ideas:
        p = keys.index(i["status"]) if i["status"] in keys else (len(keys) if i["status"] in ("business_case", "backlog") else -1)
        for j, k in enumerate(keys):
            if p >= j:
                reached_idea[k] += 1
    reached_idea["business_case"] = sum(1 for i in ideas if i["status"] == "business_case")

    phases = []
    for phase_name, kind, stages in _pipeline_phases():
        # conversion is only meaningful within a phase: cases can enter the
        # pipeline directly (auto-drafts, replicated patterns), so comparing
        # case counts against idea counts would fabricate pass rates
        prev_reached: Optional[int] = None
        stage_blocks = []
        for stage in stages:
            if kind == "idea":
                in_stage = [i for i in ideas if i["status"] == stage]
                items = [{
                    "id": i["id"], "title": i["title"],
                    "value": round(idea_value(i), 2),
                    "days_in_stage": _days_since(idea_entered(i)),
                    "owner": i.get("submitter"),
                } for i in in_stage]
                reached = reached_idea.get(stage, len(items))
                dwells = _completed_dwells(stage)
            else:
                in_stage = [c for c in cases if c["stage"] == stage]
                items = [{
                    "id": c["id"],
                    "title": c["title"].replace("[Auto-draft] ", ""),
                    "value": round((c["linked_opportunity"] or {}).get("estimated_annual_savings") or 0, 2),
                    "verified": round((c["tracking"] or {}).get("measured_annual_savings") or 0, 2),
                    "days_in_stage": _days_since(case_entered(c)),
                    "owner": db.submitter_for_case(c["id"]),
                } for c in in_stage]
                reached = case_reached(stage)
                dwells = case_dwells(stage)
            conversion = (round(reached / prev_reached, 2)
                          if prev_reached else None)
            stage_blocks.append({
                "stage": stage,
                "count": len(items),
                "value": round(sum(x["value"] for x in items), 2),
                "verified": round(sum(x.get("verified", 0) for x in items), 2),
                "items": sorted(items, key=lambda x: -(x["days_in_stage"] or 0)),
                "reached": reached,
                "conversion_from_previous": conversion,
                "median_dwell_days": _median(dwells),
                "aging": sum(1 for x in items
                             if (x["days_in_stage"] or 0) > _AGING_DAYS),
            })
            prev_reached = reached
        phases.append({"phase": phase_name, "kind": kind, "stages": stage_blocks})

    in_flight_ideas = [i for i in ideas if i["status"] in _IDEA_ORDER]
    active_cases = [c for c in cases if c["stage"] not in ("closed",)]
    return {
        "phases": phases,
        "aging_threshold_days": _AGING_DAYS,
        "terminal": {
            "backlog": sum(1 for i in ideas if i["status"] == "backlog"),
            "declined": sum(1 for i in ideas if i["status"] == "declined"),
            "closed": sum(1 for c in cases if c["stage"] == "closed"),
        },
        "totals": {
            "in_flight": len(in_flight_ideas) + len(active_cases),
            "pipeline_value": round(
                sum(idea_value(i) for i in in_flight_ideas)
                + sum((c["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
                      for c in active_cases), 2),
            "verified_value": round(sum(
                (c["tracking"] or {}).get("measured_annual_savings") or 0 for c in cases), 2),
            "end_to_end_conversion": (
                round(reached_idea["business_case"] / len(ideas), 2) if ideas else None),
        },
    }
