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

def HORIZON_TARGETS_LIVE() -> Dict[str, float]:
    """Horizon targets derive from the admin-set strategy context (old/now/new
    mapped onto delivery horizons) so every surface tells ONE balance story."""
    import json as _json
    raw = db.meta_get("strategy_context")
    t = (_json.loads(raw).get("target_onn") if raw else None) or \
        {"old": 0.3, "now": 0.5, "new": 0.2}
    return {"h1": t.get("now", 0.5), "h2": t.get("old", 0.3), "h3": t.get("new", 0.2)}


HORIZON_TARGETS = {"h1": 0.70, "h2": 0.20, "h3": 0.10}  # legacy default; see HORIZON_TARGETS_LIVE

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


def _ai_key() -> str:
    """The key powering every AI call: workspace-configured (Hub Settings)
    first, environment fallback."""
    try:
        stored = db.meta_get("anthropic_api_key")
    except Exception:
        stored = None
    import os
    return (stored or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


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


def _assist_fields(title: str, opportunities: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Structured intake suggestions for the wizard's later steps, from the
    same grounding the draft uses."""
    idea_tokens = _tokens(title)
    best = None
    for opp in opportunities or []:
        overlap = len(idea_tokens & _tokens(f"{opp['title']} {opp['category']} {opp['description']}"))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, opp)
    if best:
        opp = best[1]
        return {"beneficiary": f"The teams behind '{opp['category']}' operations",
                "pain_point": opp["description"].split(".")[0],
                "estimated_annual_benefit": opp.get("estimated_annual_savings"),
                "benefit_type": "cost_reduction", "category": opp.get("category")}
    low = title.lower()
    for keywords, problem, who, outcome in _DOMAIN_DRAFTS:
        if any(k in low for k in keywords):
            return {"beneficiary": who.capitalize(), "pain_point": problem.capitalize(),
                    "estimated_annual_benefit": None, "benefit_type": "cost_reduction",
                    "category": None}
    return {"beneficiary": None, "pain_point": None, "estimated_annual_benefit": None,
            "benefit_type": None, "category": None}


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

    if not _ai_key():
        if mode == "generate":
            return {"mode": mode, "draft": _template_draft(title, opportunities),
                    "fields": _assist_fields(title, opportunities),
                    "generated_by": "template",
                    "suggestions": ["Drafted from the hub's detected-opportunity data and "
                                    "domain templates — verify the specifics and adjust "
                                    "numbers before submitting."]}
        return {"mode": mode, "draft": description, "generated_by": "template",
                "fields": _assist_fields(title, opportunities),
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

    client = anthropic.Anthropic(api_key=_ai_key())
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
        return {"mode": mode, "generated_by": "claude",
                "fields": _assist_fields(title, opportunities), **result}
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
    if not _ai_key():
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

    client = anthropic.Anthropic(api_key=_ai_key())
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
    if not _ai_key():
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

    client = anthropic.Anthropic(api_key=_ai_key())
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


TEN_TYPES = [
    ("Profit Model", "how you make money"), ("Network", "connections with others"),
    ("Structure", "alignment of talent and assets"), ("Process", "signature methods of work"),
    ("Product Performance", "distinguishing features and functionality"),
    ("Product System", "complementary products and services"),
    ("Service", "support and enhancements around offerings"),
    ("Channel", "how offerings reach users"), ("Brand", "representation of offerings"),
    ("Customer Engagement", "distinctive interactions fostered"),
]

_FUTURES_FRAMES = {
    "1-3y": ("Near horizon — extrapolate current signals",
             ["AI agents absorb routine knowledge work", "Cost scrutiny reshapes vendor stacks",
              "Regulation catches up to automated decisions"]),
    "3-7y": ("Mid horizon — second-order effects compound",
             ["Workflows reorganize around human-AI teams", "Data ecosystems consolidate across firms",
              "Sustainability constraints become pricing inputs"]),
    "7-15y": ("Far horizon — reimagine the future (Diana-style rethinking)",
              ["Industry boundaries dissolve into capability networks",
               "Autonomous operations become the default, humans govern by exception",
               "Value migrates from products to verified outcomes"]),
}


_PEER_SETS = {
    "pharmaceuticals": ["Pfizer", "Novartis", "Merck", "Bristol Myers Squibb", "AstraZeneca"],
    "healthcare": ["UnitedHealth", "CVS Health", "Cigna", "Humana"],
    "financial services": ["JPMorgan Chase", "Bank of America", "Goldman Sachs", "Morgan Stanley"],
    "insurance": ["Allstate", "Progressive", "Travelers", "Chubb"],
    "retail": ["Walmart", "Target", "Costco", "Amazon"],
    "manufacturing": ["Siemens", "GE", "Honeywell", "3M"],
    "technology": ["Microsoft", "Google", "Amazon", "Salesforce"],
    "energy": ["ExxonMobil", "Chevron", "Shell", "BP"],
    "telecom": ["Verizon", "AT&T", "T-Mobile", "Comcast"],
    "automotive": ["Toyota", "Volkswagen", "GM", "Ford"],
    "food & beverage": ["Nestle", "PepsiCo", "Coca-Cola", "Mondelez"],
}
_COMPANY_INDUSTRY = {
    "abbvie": "pharmaceuticals", "pfizer": "pharmaceuticals", "merck": "pharmaceuticals",
    "novartis": "pharmaceuticals", "starbucks": "food & beverage", "pepsico": "food & beverage",
    "walmart": "retail", "target": "retail", "amazon": "retail", "jpmorgan": "financial services",
    "unitedhealth": "healthcare", "cvs": "healthcare", "verizon": "telecom", "at&t": "telecom",
    "toyota": "automotive", "ford": "automotive", "microsoft": "technology",
    "salesforce": "technology", "siemens": "manufacturing", "ge": "manufacturing",
    "exxon": "energy", "chevron": "energy", "allstate": "insurance", "progressive": "insurance",
}


def _peers_for(subject: str, industry: str = "") -> list:
    low = (subject or "").lower()
    ind = (industry or "").lower()
    for name, mapped in _COMPANY_INDUSTRY.items():
        if name in low:
            peers = [p for p in _PEER_SETS[mapped] if p.lower() not in low]
            return peers[:4]
    for key in _PEER_SETS:
        if key in low or key in ind:
            return _PEER_SETS[key][:4]
    return []


def competitive_report(intake: Dict[str, Any], force_template: bool = False) -> Dict[str, Any]:
    """Full structured competitive analysis: exec summary, market overview,
    competitor profiles, comparison matrix, positioning map, SWOT, gaps,
    threats, prioritized recommendations — every claim confidence-labeled.
    AI+web when keyed; a complete, realistic demo report otherwise."""
    import os
    product = intake.get("product") or intake.get("segment") or "Our company"
    competitors = [c for c in (intake.get("competitors") or []) if c.strip()][:6]
    if _ai_key() and not force_template:
        try:
            import anthropic
            from pydantic import BaseModel
            from typing import List as TList, Optional as TOpt

            class Score(BaseModel):
                criterion: str
                rating: str
                justification: str
                confidence: str

            class Company(BaseModel):
                name: str
                scores: TList[Score]

            class Placement(BaseModel):
                company: str
                x: float
                y: float

            class Profile(BaseModel):
                name: str
                snapshot: str
                ideal_customer: str
                value_prop: str
                pricing_model: str
                gtm_motion: str
                notable_moves: str
                confidence: str

            class Rec(BaseModel):
                title: str
                based_on_finding: str
                impact: str
                effort: str
                priority: int

            class Report(BaseModel):
                executive_summary: TList[str]
                top_recommendation: str
                market_overview: str
                trends: TList[str]
                profiles: TList[Profile]
                comparison_matrix_criteria: TList[str]
                comparison_matrix: TList[Company]
                pricing_comparison: str
                positioning_x_axis: str
                positioning_y_axis: str
                positioning: TList[Placement]
                white_space: str
                swot_strengths: TList[str]
                swot_weaknesses: TList[str]
                swot_opportunities: TList[str]
                swot_threats: TList[str]
                gaps_and_opportunities: TList[str]
                threats_to_monitor: TList[str]
                recommendations: TList[Rec]
                thin_areas: TList[str]
                suggested_research: TList[str]

            r = anthropic.Anthropic(api_key=_ai_key()).messages.parse(
                model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
                system=(f"You are a senior competitive intelligence analyst. Analyze the company {product} "
                        f"({intake.get('description', '')}) against peer COMPANIES: "
                        f"{', '.join(competitors) or 'the 5 closest peer companies, which you must identify and justify'} "
                        f"for an audience of {intake.get('audience', 'leadership')}, to inform: "
                        f"{intake.get('decision', 'strategy')}. Target segment: {intake.get('segment', 'unspecified')}. "
                        "This is company-vs-company analysis (strategy, operations, innovation posture), not product feature comparison. Research each peer company with web search. Score the matrix "
                        "strong/adequate/weak on the 6-10 criteria buyers actually weigh. Positioning "
                        "x,y in [-1,1] on the two most differentiating axes. Label every claim's "
                        "confidence as fact, inference, or assumption — never present a guess as fact. "
                        "Where you could not verify, say so in thin_areas. Be specific; no filler."),
                messages=[{"role": "user", "content":
                           f"Notes from the requester: {intake.get('notes') or '(none)'}"}],
                output_format=Report)
            out = r.parsed_output.model_dump()
            out["generated_by"] = "claude"
            return out
        except Exception:
            pass
    # demo mode: complete, realistic, clearly labeled
    known = _peers_for(product, intake.get("segment") or "")
    comps = competitors or known or ["Peer Company A", "Peer Company B", "Peer Company C"]
    criteria = ["Innovation velocity", "Digital & AI maturity", "Customer experience",
                "Cost position", "Talent & culture", "Partner ecosystem"]
    strengths = {comps[0]: [0, 3], comps[1] if len(comps) > 1 else comps[0]: [3, 5],
                 comps[2] if len(comps) > 2 else comps[0]: [4]}
    def rate(comp, i):
        if comp == product:
            return ("strong" if i in (0, 2) else "adequate" if i in (1, 4) else "weak",
                    f"Directional self-assessment on '{criteria[i]}' — replace with your own "
                    "evidence from the maturity assessment tab", "assumption")
        good = strengths.get(comp, [3])
        return ("strong" if i in good else "adequate" if (i + len(comp)) % 3 else "weak",
                f"Directional read on {comp} for '{criteria[i]}' — validate with primary research",
                "assumption")
    companies = [product] + comps
    matrix = [{"name": c, "scores": [
        {"criterion": criteria[i], "rating": rate(c, i)[0],
         "justification": rate(c, i)[1], "confidence": rate(c, i)[2]}
        for i in range(len(criteria))]} for c in companies]
    place = {product: (0.7, 0.65)}
    for j, c in enumerate(comps):
        place[c] = (round(-0.6 + j * 0.35, 2), round(-0.4 + j * 0.15, 2))
    return {
        "generated_by": "template",
        "executive_summary": [
            f"{product} can out-innovate on speed of evidence: measurable experiments beat peer announcements",
            f"{comps[0]} and {comps[1] if len(comps) > 1 else 'peers'} likely lead on scale and brand — hard to match head-on, flankable on velocity",
            "Across the industry, advantage is shifting from asset scale to innovation velocity and verified outcomes"],
        "top_recommendation": f"Compete on innovation velocity: run more verified experiments per quarter "
                              f"than {comps[0]} announces initiatives — and publish the evidence.",
        "market_overview": "Innovation management platforms (~$1-2B, growing low double digits) are "
                           "consolidating from idea collection toward measurable portfolio outcomes.",
        "trends": ["Buyers demand verified outcomes over engagement metrics",
                   "AI moves from assistant to engine (drafting, triage, red-teaming)",
                   "Procurement gates tighten: SOC 2, SSO, data residency as table stakes"],
        "profiles": [{"name": c, "snapshot": f"{c}: established innovation-management vendor",
                      "ideal_customer": "10k+ employee enterprise with a formal innovation office",
                      "value_prop": "Breadth, configurability, and reference customers",
                      "pricing_model": "Enterprise annual license, sales-led",
                      "gtm_motion": "Direct enterprise sales with services partners",
                      "notable_moves": "AI-assistant features announced in the last year",
                      "confidence": "assumption"} for c in comps],
        "comparison_matrix_criteria": criteria,
        "comparison_matrix": matrix,
        "pricing_comparison": f"Incumbents sell opaque enterprise licenses; {product} can wedge with "
                              "transparent self-serve pricing and a free workspace tier.",
        "positioning_x_axis": "Breadth of suite →",
        "positioning_y_axis": "Proof of outcomes →",
        "positioning": [{"company": c, "x": xy[0], "y": xy[1]} for c, xy in place.items()],
        "white_space": "High-proof / focused quadrant is empty: nobody else computes verified value "
                       "from customer data. That corner is ours to name.",
        "swot_strengths": ["Verified value ledger (structural differentiator)",
                           "AI that does work, not just tags it", "Same-day proof-of-value demo"],
        "swot_weaknesses": ["Ephemeral storage / no SSO yet", "No reference customers",
                            "Single-team vendor risk in procurement eyes"],
        "swot_opportunities": ["CFO-led buying committees", "Displace activity-metric renewals",
                               "Publish honest-innovation-accounting standard"],
        "swot_threats": ["Incumbent bolts on 'verified-ish' reporting", "Procurement disqualification",
                         "Platform players (ServiceNow) bundling innovation modules"],
        "gaps_and_opportunities": [
            "No incumbent computes value from source data — 12-18 month structural lead (inference)",
            "Kill-friendly economics (learning dividends) is unoccupied positioning (fact: none market it)",
            "Metered funding tranches match how CFOs already think (inference)"],
        "threats_to_monitor": [
            "Watch: incumbent M&A of analytics vendors (early sign: partnership announcements)",
            "Watch: RFP templates adding 'outcome verification' as a line item — moat becomes stakes"],
        "recommendations": [
            {"title": "Close procurement disqualifiers", "based_on_finding": "Enterprise readiness gap",
             "impact": "high", "effort": "medium", "priority": 1},
            {"title": "Lead demos with the ledger", "based_on_finding": "White space on proof axis",
             "impact": "high", "effort": "low", "priority": 2},
            {"title": "Publish the methodology as a standard", "based_on_finding": "Honesty positioning unoccupied",
             "impact": "medium", "effort": "low", "priority": 3}],
        "thin_areas": ["Competitor pricing specifics unverified (demo mode — no web research)",
                       "Win/loss data absent"],
        "suggested_research": ["5 win/loss interviews with innovation-office buyers",
                               "Analyst-firm briefings for current competitive scores"],
    }


def tentypes_concepts(topic: str, force_template: bool = False,
                      types: Optional[List[int]] = None) -> Dict[str, Any]:
    """Breakthrough concepts per the Keeley discipline: each combines >=3
    types, scored 1-5 discriminatingly, with a riskiest-assumption experiment
    and kill metric."""
    import os
    if _ai_key() and not force_template:
        try:
            import anthropic
            from pydantic import BaseModel
            from typing import List as TList

            class Concept(BaseModel):
                name: str
                narrative: str
                types_combined: TList[int]
                target_customer: str
                revenue_logic: str
                orthodoxy_broken: str
                impact: int
                differentiation: int
                feasibility: int
                fit: int

            class Out(BaseModel):
                concepts: TList[Concept]
                recommended: TList[str]
                recommendation_reasoning: str
                experiments: TList[Dict[str, str]]

            r = anthropic.Anthropic(api_key=_ai_key()).messages.parse(
                model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
                system=("Senior innovation strategist, expert in Keeley's Ten Types. Your job "
                        "is COMBINATORIAL: fuse the specified types into net-new concepts that "
                        "exist nowhere yet — the novelty must come from the intersection of the "
                        "types, not from any single one. Name the mechanism of each fusion. "
                        "Score 1-5 using the full range. Each experiment names the riskiest "
                        "assumption, design, duration, and a kill metric."),
                messages=[{"role": "user", "content":
                           f"Business context: {topic}. "
                           + (f"Combine EXACTLY these types in every concept: "
                              f"{[f'{t}:{TEN_TYPES[t-1][0]}' for t in types]}. "
                              if types else
                              "Choose three unusual 3-4 type combinations yourself; avoid "
                              "combinations common in the literature.")}],
                output_format=Out)
            out = r.parsed_output.model_dump()
            out["generated_by"] = "claude"
            return out
        except Exception:
            pass
    if types:
        names = [TEN_TYPES[t - 1][0] for t in types if 1 <= t <= 10]
        descs = [TEN_TYPES[t - 1][1] for t in types if 1 <= t <= 10]
        fusion = " × ".join(names)
        return {"generated_by": "template", "concepts": [{
            "name": f"{fusion} fusion for {topic}",
            "types_combined": types,
            "narrative": (f"Force the intersection: what would {topic} look like if you changed "
                          + ", ".join(descs[:-1]) + f", and {descs[-1]} in ONE move? The novelty "
                          "lives where these constraints meet — describe the mechanism that "
                          "satisfies all of them simultaneously, then name who pays and why."),
            "target_customer": "The segment most underserved by single-type competitors",
            "revenue_logic": f"Monetize the {names[0].lower()} change; defend with the "
                             f"{names[-1].lower()} change",
            "orthodoxy_broken": f"'{names[0]} and {names[-1]} are separate decisions'",
            "impact": 4, "differentiation": 5, "feasibility": 3, "fit": 4}],
            "recommended": [f"{fusion} fusion for {topic}"],
            "recommendation_reasoning": "Chosen combination is unusual by construction — "
                                        "differentiation is structural, feasibility is the bet.",
            "experiments": [{"concept": f"{fusion} fusion for {topic}",
                             "riskiest_assumption": "The intersection creates value a single "
                             "type wouldn't", "experiment": "Paper-prototype the fused offer and "
                             "price-test it against the single-type alternative with 5 customers",
                             "duration_days": "30",
                             "kill_metric": "No customer prefers the fusion at equal price"}]}
    return {"generated_by": "template", "concepts": [
        {"name": "Outcome-guaranteed service tier", "types_combined": [1, 7, 10],
         "narrative": f"For {topic}: customers stop buying effort and buy a measured result — "
                      "priced on verified outcomes, serviced proactively, engagement built on a "
                      "live evidence dashboard.",
         "target_customer": "Value-skeptical enterprise buyers", "revenue_logic":
         "Premium tier priced at a share of verified savings", "orthodoxy_broken":
         "'We bill for activity, not results'", "impact": 5, "differentiation": 5,
         "feasibility": 3, "fit": 5},
        {"name": "Partner-operated delivery network", "types_combined": [2, 3, 8],
         "narrative": f"Certified partners run {topic} delivery in regions we will never staff — "
                      "we keep the platform and the evidence layer, they keep the local margin.",
         "target_customer": "Mid-market outside our geography", "revenue_logic":
         "Platform fee per partner engagement", "orthodoxy_broken":
         "'Quality requires our own people'", "impact": 4, "differentiation": 3,
         "feasibility": 4, "fit": 3},
        {"name": "Open evidence standard", "types_combined": [4, 9, 6],
         "narrative": f"Publish our measurement method for {topic} as an open standard; the brand "
                      "becomes the referee and the product the reference implementation.",
         "target_customer": "Analysts, regulators, and their followers", "revenue_logic":
         "Standard is free; certification and tooling are not", "orthodoxy_broken":
         "'Methodology is proprietary IP'", "impact": 4, "differentiation": 4,
         "feasibility": 4, "fit": 4}],
        "recommended": ["Outcome-guaranteed service tier"],
        "recommendation_reasoning": "Highest impact x differentiation and it compounds the "
                                    "platform's structural advantage (verified value); feasibility "
                                    "risk is contained by the experiment below.",
        "experiments": [
            {"concept": "Outcome-guaranteed service tier",
             "riskiest_assumption": "Customers will contract on verified-outcome pricing",
             "experiment": "Offer the tier to 3 friendly accounts as a signed LOI pilot",
             "duration_days": "45", "kill_metric": "Fewer than 2 of 3 sign the LOI"}]}


def ideate_studio(kind: str, topic: str, horizon: str = "3-7y",
                  force_template: bool = False) -> Dict[str, Any]:
    """Futures / competitive / maturity / ten-types studios. AI-driven with a
    key; labeled template frames otherwise."""
    import os
    has_ai = bool(_ai_key()) and not force_template
    if has_ai:
        try:
            import anthropic
            from pydantic import BaseModel
            from typing import List as TList

            class Studio(BaseModel):
                narrative: str
                items: TList[Dict[str, str]]
                idea_seeds: TList[str]

            prompts = {
                "futures": f"Act as futurist Frank Diana: for horizon {horizon}, scan signals on "
                           f"'{topic}', derive implications, and reimagine the future state. items: "
                           "[{title, detail}] as signals->implications; 3 idea_seeds.",
                "competitive": f"Competitive analysis of '{topic}': items [{{title, detail}}] covering "
                               "their strengths, recent moves, and our exploitable gaps; 3 idea_seeds.",
                "maturity": f"High-level maturity assessment of our industry position on '{topic}': "
                            "items [{title, detail}] where title='Dimension — level N/5'; 3 idea_seeds.",
                "ten_types": f"Apply Larry Keeley's Ten Types of Innovation to '{topic}': one item per "
                             "type [{title: type name, detail: the specific opportunity}]; 3 idea_seeds.",
            }
            r = anthropic.Anthropic(api_key=_ai_key()).messages.parse(
                model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 4}],
                messages=[{"role": "user", "content": prompts[kind]}], output_format=Studio)
            out = r.parsed_output.model_dump()
            out["generated_by"] = "claude"
            return out
        except Exception:
            pass
    if kind == "futures":
        frame, signals = _FUTURES_FRAMES.get(horizon, _FUTURES_FRAMES["3-7y"])
        return {"generated_by": "template", "narrative":
                f"{frame}. Reimagined: '{topic}' stops being a process someone runs and becomes an "
                "outcome the enterprise guarantees — measured, autonomous where safe, human-governed "
                "where it matters.",
                "items": [{"title": sig, "detail": f"Implication for {topic}: rehearse this future "
                           "now with a low-cost experiment rather than reacting to it later."}
                          for sig in signals],
                "idea_seeds": [f"Run a pre-mortem: our {topic} strategy failed in {horizon} — why?",
                               f"Prototype the {horizon} version of {topic} as a one-week probe",
                               f"Name the capability we'd need if {topic} became fully autonomous"]}
    if kind == "competitive":
        peers = _peers_for(topic)
        peer_line = (f"Closest peers: {', '.join(peers)}." if peers else "")
        return {"generated_by": "template", "narrative":
                f"Competitive frame for '{topic}'. {peer_line}",
                "items": [{"title": "Their likely strength", "detail": f"Scale and installed base around {topic}."},
                          {"title": "Their likely blind spot", "detail": "Verified outcomes — incumbents report activity, not evidence."},
                          {"title": "Our exploitable gap", "detail": f"Move faster from detection to funded experiment on {topic}."}],
                "idea_seeds": [f"Win-back play targeting {topic} customers stuck in legacy contracts",
                               f"Publish verified-outcome benchmarks where {topic} competitors publish claims",
                               f"Partner where {topic} leaders are weakest instead of building"]}
    if kind == "maturity":
        dims = ["Strategy & ambition", "Data & measurement", "Process & governance",
                "Talent & culture", "Technology & automation"]
        return {"generated_by": "template", "narrative":
                f"Directional maturity read on '{topic}' — validate in a workshop.",
                "items": [{"title": f"{d} — level {2 + (i % 3)}/5",
                           "detail": f"Typical enterprise sits at level {2 + (i % 3)} on {d.lower()} "
                                     f"for {topic}; next level requires making it measurable and owned."}
                          for i, d in enumerate(dims)],
                "idea_seeds": [f"90-day plan to move one {topic} dimension up a level",
                               f"Baseline {topic} metrics before investing further",
                               f"Assign a single owner for {topic} maturity"]}
    if kind == "ten_types":
        return {"generated_by": "template", "narrative":
                f"Keeley Ten Types scan of '{topic}': innovation compounds when you combine 3+ types "
                "beyond product performance.",
                "items": [{"title": name, "detail": f"{desc.capitalize()}: where could '{topic}' "
                           f"change the {name.lower()} rather than the product?"}
                          for name, desc in TEN_TYPES],
                "idea_seeds": [f"Pick two non-product types and prototype a {topic} play combining them",
                               f"Score competitors on the ten types to find the empty spaces around {topic}",
                               f"Reframe the top detected opportunity through a profit-model lens"]}
    raise ValueError(f"unknown studio kind '{kind}'")


# --------------------------------------------------------------- MVP workflow

MVP_STAGES = ["design", "build", "test", "deploy", "validate"]

MVP_STAGE_META = {
    "design": {"label": "Design", "goal": "Define the smallest product that proves the value claim",
               "ai_role": "AI drafts the PRD, user stories, and scope cuts from the business case"},
    "build": {"label": "Build", "goal": "Assemble the MVP with the leanest viable architecture",
              "ai_role": "AI proposes the architecture, build-vs-buy calls, and pair-programs the implementation"},
    "test": {"label": "Test", "goal": "Prove the MVP works for real users before exposure",
             "ai_role": "AI generates the test plan, edge cases, and UAT scripts from the user stories"},
    "deploy": {"label": "Deploy", "goal": "Ship safely with a rollback path and staged exposure",
               "ai_role": "AI writes the runbook, rollout gates, and comms from the deploy plan"},
    "validate": {"label": "Validate", "goal": "Measure real outcomes against the business case and decide the go-to-market",
                 "ai_role": "AI advises on GTM positioning and reads the evidence for a pivot/persevere call"},
}


def _mvp_case_grounding(case: Dict[str, Any], fin: Dict[str, Any]) -> str:
    money = lambda v: f"${v:,.0f}" if isinstance(v, (int, float)) else "unstated"  # noqa: E731
    return (f"Business case: {case.get('title')}\n"
            f"Description: {(case.get('description') or '')[:600]}\n"
            f"Annual benefit: {money(fin.get('annual_benefit'))}; "
            f"implementation cost: {money(fin.get('implementation_cost'))}; "
            f"NPV: {money(fin.get('npv'))}; ROI: {fin.get('roi_pct')}%; "
            f"payback: {fin.get('payback_months')} months.\n"
            f"Stage: {case.get('stage')}; category: "
            f"{(case.get('linked_opportunity') or {}).get('category') or 'uncategorized'}.")


def mvp_stage_pack(case: Dict[str, Any], fin: Dict[str, Any], stage: str,
                   force_template: bool = False) -> Dict[str, Any]:
    """One MVP workflow stage artifact (design/build/test/deploy/validate):
    AI-drafted from the case's own financial grounding when a key is set,
    honest labeled template otherwise."""
    if stage not in MVP_STAGES:
        raise ValueError(f"unknown MVP stage '{stage}'")
    if _ai_key() and not force_template:
        try:
            import anthropic
            from pydantic import BaseModel
            from typing import List as TList

            class StagePack(BaseModel):
                summary: str
                sections: TList[Dict[str, str]]
                checklist: TList[str]
                ai_leverage: TList[str]

            briefs = {
                "design": "Draft the MVP DESIGN pack: problem statement, target user, MVP scope "
                          "(explicitly in vs out), 5-8 user stories with acceptance criteria, the "
                          "riskiest assumption to test, and success metrics traceable to the stated "
                          "annual benefit.",
                "build": "Draft the MVP BUILD pack: leanest viable architecture, build-vs-buy calls, "
                         "a 2-3 sprint plan, the smallest team that can ship it, and tooling choices.",
                "test": "Draft the MVP TEST pack: test strategy, acceptance test list per user story, "
                        "edge cases and failure modes, a UAT script for 3-5 pilot users, and exit "
                        "criteria for go/no-go.",
                "deploy": "Draft the MVP DEPLOY pack: environment plan, staged rollout with exposure "
                          "gates, feature flags, rollback procedure, and a stakeholder comms plan.",
                "validate": "Draft the MVP VALIDATE pack: instrumentation plan tying usage to the "
                            "business-case benefit, leading vs lagging indicators, go-to-market advice "
                            "(positioning, first customers, pricing posture, channels), and explicit "
                            "pivot/persevere/kill criteria with thresholds.",
            }
            r = anthropic.Anthropic(api_key=_ai_key()).messages.parse(
                model="claude-opus-4-8", max_tokens=16000, thinking={"type": "adaptive"},
                messages=[{"role": "user", "content":
                           f"{_mvp_case_grounding(case, fin)}\n\n{briefs[stage]}\n"
                           "sections: [{title, detail}] — 4-7 sections, concrete and specific to THIS "
                           "case, no generic filler. checklist: 5-8 actionable done-criteria. "
                           "ai_leverage: 3-5 specific ways the team should use AI in this stage."}],
                output_format=StagePack)
            out = r.parsed_output.model_dump()
            out["generated_by"] = "claude"
            out["stage"] = stage
            out["meta"] = MVP_STAGE_META[stage]
            return out
        except Exception:
            pass
    title = case.get("title") or "the MVP"
    benefit = fin.get("annual_benefit") or 0
    meta = MVP_STAGE_META[stage]
    packs: Dict[str, Dict[str, Any]] = {
        "design": {
            "summary": f"Design the smallest version of '{title}' that can prove "
                       f"${benefit:,.0f}/yr is real — cut everything that doesn't test that claim.",
            "sections": [
                {"title": "Problem statement", "detail": (case.get("description") or "")[:300] or
                 "State the pain in one sentence a user would recognize."},
                {"title": "MVP scope — in", "detail": "The one workflow that produces the measurable "
                 "benefit; a single user role; manual fallbacks everywhere else."},
                {"title": "MVP scope — out", "detail": "Integrations, admin tooling, scale hardening, "
                 "and every second persona. Deferring these is the point of an MVP."},
                {"title": "Riskiest assumption", "detail": "Users will change their current behavior "
                 "to capture the benefit. Design the MVP so week one confirms or kills this."},
                {"title": "Success metrics", "detail": f"Pick 1-2 metrics that ladder directly to the "
                 f"${benefit:,.0f}/yr claim; baseline them BEFORE build so validation is honest."},
            ],
            "checklist": ["Problem statement signed by the sponsor", "Scope in/out list frozen",
                          "5+ user stories with acceptance criteria", "Riskiest assumption named",
                          "Success metrics baselined pre-build"],
        },
        "build": {
            "summary": f"Build '{title}' with the leanest stack that survives a pilot — "
                       "optimize for iteration speed, not permanence.",
            "sections": [
                {"title": "Architecture", "detail": "One service, one datastore, boring technology. "
                 "Every architectural flourish delays the validation date."},
                {"title": "Build vs buy", "detail": "Buy or reuse anything that isn't the "
                 "differentiating workflow; build only what tests the value claim."},
                {"title": "Sprint plan", "detail": "Sprint 1: walking skeleton end-to-end. Sprint 2: "
                 "the benefit-producing workflow. Sprint 3: instrumentation and pilot hardening."},
                {"title": "Team", "detail": "Smallest team that can ship: one product owner, 1-2 "
                 "builders, part-time design. Add people after validation, not before."},
            ],
            "checklist": ["Walking skeleton demo-able", "Core workflow functional end-to-end",
                          "Instrumentation events firing", "No unbought undifferentiated components",
                          "Pilot environment provisioned"],
        },
        "test": {
            "summary": f"Prove '{title}' works for the pilot group before anyone else sees it — "
                       "test the workflow, not just the code.",
            "sections": [
                {"title": "Test strategy", "detail": "Automated checks on the benefit-producing path; "
                 "manual exploratory passes on everything else. Coverage follows risk, not vanity."},
                {"title": "Acceptance tests", "detail": "One acceptance test per user story from the "
                 "design pack; a story without a passing test is not done."},
                {"title": "Edge cases", "detail": "Empty states, bad input, permission boundaries, and "
                 "the first-day experience of a user who received no training."},
                {"title": "UAT script", "detail": "3-5 pilot users complete the core workflow "
                 "unassisted while you watch; every stumble is a finding."},
            ],
            "checklist": ["Acceptance test per story passing", "Edge-case list executed",
                          "UAT run with 3+ real users", "Findings triaged fix/defer",
                          "Go/no-go exit criteria met"],
        },
        "deploy": {
            "summary": f"Ship '{title}' in stages with a tested way back — exposure is earned, "
                       "not defaulted.",
            "sections": [
                {"title": "Rollout stages", "detail": "Pilot group first, then a bounded cohort, then "
                 "general availability — each gate requires the previous stage's metrics to hold."},
                {"title": "Feature flags", "detail": "The benefit-producing workflow ships behind a "
                 "flag so rollback is a toggle, not a redeploy."},
                {"title": "Rollback", "detail": "Rehearse the rollback before go-live. If reverting "
                 "takes longer than an hour, the rollout plan is not ready."},
                {"title": "Comms", "detail": "Tell pilot users what changes, what to do when stuck, "
                 "and how their feedback reaches the team same-day."},
            ],
            "checklist": ["Pilot cohort named", "Flags wired on core workflow",
                          "Rollback rehearsed", "Support/comms channel live",
                          "Exposure gates defined with metrics"],
        },
        "validate": {
            "summary": f"Measure '{title}' against the ${benefit:,.0f}/yr claim and make the "
                       "pivot/persevere call with evidence, not enthusiasm.",
            "sections": [
                {"title": "Instrumentation", "detail": "Bind the success metrics to source data (ROI "
                 "Tracking metric bindings) so realized value is observed, never asserted."},
                {"title": "Leading indicators", "detail": "Adoption and repeat usage in weeks 1-4 "
                 "predict whether the annual benefit will materialize; watch these first."},
                {"title": "Go-to-market", "detail": "Position around the verified outcome, not the "
                 "feature list. First customers are the pilot's loudest advocates; price against "
                 "the measured benefit, not cost-plus."},
                {"title": "Pivot / persevere / kill", "detail": "Set thresholds now: persevere if "
                 "leading indicators track to plan, pivot if users engage but value doesn't follow, "
                 "kill if adoption stalls after two corrective iterations."},
            ],
            "checklist": ["Metric bindings observing actuals", "4-week leading-indicator read done",
                          "GTM positioning drafted from evidence", "Pivot/persevere thresholds set",
                          "Decision logged with the sponsor"],
        },
    }
    pack = packs[stage]
    pack["ai_leverage"] = {
        "design": ["Generate the PRD and user stories from the business case, then edit — don't start blank",
                   "Ask AI to argue AGAINST each scope item; cut what survives weakly",
                   "Draft interview scripts for validating the riskiest assumption"],
        "build": ["AI pair-programming for the walking skeleton and boilerplate",
                  "Generate the architecture decision records with trade-offs stated",
                  "Have AI review each PR for scope creep against the design pack"],
        "test": ["Generate acceptance tests directly from the user stories",
                 "Ask AI to enumerate edge cases a hostile first-time user would hit",
                 "Draft the UAT script and synthesize the findings into fix/defer"],
        "deploy": ["Generate the runbook and rollback procedure, then rehearse them",
                   "Draft stage-gate criteria and the pilot comms pack",
                   "Have AI review deploy configs for single points of failure"],
        "validate": ["Analyze pilot usage data for adoption patterns and drop-off points",
                     "Draft GTM positioning from the measured (not claimed) outcomes",
                     "Stress-test the pivot/persevere call: ask AI to argue the opposite case"],
    }[stage]
    pack["generated_by"] = "template"
    pack["stage"] = stage
    pack["meta"] = meta
    return pack


def ai_evaluate_idea(idea: Dict[str, Any],
                     opportunities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Deeper AI validation of one idea: measurability check, categorization,
    missing intake information, duplicate risk. Falls back to a deterministic
    assessment when no API key is configured."""
    import os

    heuristic = (idea.get("assessment") or {})
    if not _ai_key():
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
    client = anthropic.Anthropic(api_key=_ai_key())
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
        bucket["target_share"] = HORIZON_TARGETS_LIVE().get(h)

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
    old_keys = workflow_keys()
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
    # migrate ideas stranded at removed gates to the nearest surviving earlier
    # gate (by the OLD ordering), so nothing vanishes from the queues while
    # cost-of-delay keeps billing for it
    new_keys = [c["key"] for c in cleaned]
    removed = [k for k in old_keys if k not in new_keys]
    if removed:
        for idea in db.list_ideas():
            if idea["status"] in removed:
                idx = old_keys.index(idea["status"])
                target = next((k for k in reversed(old_keys[:idx]) if k in new_keys),
                              new_keys[0])
                db.update_idea(idea["id"], target)
                db.add_workflow_event("idea", idea["id"], "migrate", None,
                                      f"gate '{idea['status']}' removed from workflow")

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
