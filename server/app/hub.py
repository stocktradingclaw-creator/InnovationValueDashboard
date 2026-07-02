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
    db.meta_set("scoring_config", json.dumps(merged))
    return merged


# --------------------------------------------------------------- governance

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
    total_weight = sum(weights.values()) or 1.0
    score = round(100 * (
        weights["impact"] * impact_score
        + weights["data_grounding"] * grounding_score
        + weights["alignment"] * alignment_score
        + weights["completeness"] * completeness_score
        + weights.get("desirability", 0) * desirability_score
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
        },
        "derived_category": derived_category,
        "estimated_annual_benefit": benefit,
        "guardrail_flags": flags,
        "enrichment": enrichment,
        "recommendation": recommendation,
        "rationale": rationale,
    }


# ------------------------------------------------------------ AI evaluation

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

    promoted = sum(1 for i in ideas if i["status"] == "promoted")
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
