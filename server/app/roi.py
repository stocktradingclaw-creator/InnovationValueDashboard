"""Business-case digestion: free text in, structured ROI measurement plan out.

Uses the Claude API with structured output (messages.parse + Pydantic).
Falls back to a deterministic template when no API key is configured so
the app remains demoable offline.
"""
import os
from typing import List, Optional

from pydantic import BaseModel, Field

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """You are a value-engineering analyst at an IT consultancy. \
Customers submit business cases for improvement ideas (automation, consolidation, \
modernization, process change). Your job is to digest the business case and design \
the best practical way to measure the ROI of the idea AFTER it has been implemented.

Ground rules:
- Derive value drivers from what the business case actually claims, not generic benefits.
- Every KPI must be measurable from data sources a typical enterprise has \
(ERP, CMDB, ITSM, cloud billing, HR time tracking, monitoring tools). Name the source.
- Define the baseline explicitly: what to measure BEFORE go-live, over what window, \
so post-implementation comparison is valid. Call out seasonality if relevant.
- Mix leading indicators (early signals the change is working) with lagging indicators \
(realized financial outcomes).
- The ROI formula must use the KPIs you defined. Keep it computable.
- Be honest about measurement risks (attribution, baseline drift, behavior change).
- Classify each KPI's objectivity honestly: 'hard' only if it can be computed directly \
from a system of record (ledger totals, billing exports, ticket counts); 'medium' if it \
is system data combined with assumptions (e.g. hours x blended rate); 'soft' if it relies \
on surveys, estimates, or self-reporting. Do not launder soft metrics as hard ones.
- Audit the business case: list any value claims that cannot be measured from a named \
data source. An empty list means every claim is measurable."""


class KPI(BaseModel):
    name: str
    formula: str = Field(description="How the KPI is computed, using available fields")
    baseline_method: str = Field(description="How and over what window to capture the pre-implementation baseline")
    target: str = Field(description="What success looks like, with a number where possible")
    data_sources: List[str]
    cadence: str = Field(description="How often to measure, e.g. monthly")
    indicator_type: str = Field(description="'leading' or 'lagging'")
    objectivity: str = Field(
        description="'hard' (computed from a system of record), 'medium' (system data "
        "plus assumptions), or 'soft' (surveys, estimates, self-reporting)"
    )


class ValueDriver(BaseModel):
    name: str
    driver_type: str = Field(description="cost_reduction | revenue_growth | productivity | risk_avoidance")
    description: str


class ROIPlan(BaseModel):
    summary: str = Field(description="2-3 sentence digest of the business case and the measurement approach")
    value_drivers: List[ValueDriver]
    kpis: List[KPI]
    baseline_plan: str
    roi_formula: str
    measurement_cadence: str
    measurement_duration: str = Field(description="How long to measure before declaring the ROI verdict")
    assumptions: List[str]
    measurement_risks: List[str]
    unmeasurable_claims: List[str] = Field(
        description="Value claims made in the business case that cannot be measured "
        "from any named data source; empty if all claims are measurable"
    )


def _template_plan(title: str, description: str, estimated_cost: Optional[float]) -> ROIPlan:
    """Deterministic fallback used when no ANTHROPIC_API_KEY is configured."""
    cost_note = (
        f"implementation cost of ${estimated_cost:,.0f}" if estimated_cost else "implementation cost (to be captured at go-live)"
    )
    return ROIPlan(
        summary=(
            f"Template plan for '{title}' (generated without AI — set ANTHROPIC_API_KEY for a "
            f"tailored plan). Measures realized savings against the {cost_note}."
        ),
        value_drivers=[
            ValueDriver(
                name="Operating cost reduction",
                driver_type="cost_reduction",
                description="Direct reduction in run costs attributable to the initiative.",
            ),
            ValueDriver(
                name="Productivity gain",
                driver_type="productivity",
                description="Staff hours released from manual effort, valued at blended labor rate.",
            ),
        ],
        kpis=[
            KPI(
                name="Monthly run cost of affected scope",
                formula="Sum of monthly costs for the systems/processes in scope",
                baseline_method="Average of the 3 months prior to go-live",
                target="Reduction consistent with the business case claim",
                data_sources=["ERP financials", "Cloud billing"],
                cadence="monthly",
                indicator_type="lagging",
                objectivity="hard",
            ),
            KPI(
                name="Manual effort hours in scope",
                formula="Hours logged against the affected process per month",
                baseline_method="3-month pre-implementation average from time tracking or ticket volumes",
                target="Material reduction within 2 quarters",
                data_sources=["ITSM tickets", "Time tracking"],
                cadence="monthly",
                indicator_type="leading",
                objectivity="medium",
            ),
        ],
        baseline_plan=(
            "Capture 3 months of pre-implementation data for each KPI before go-live. "
            "Freeze the baseline and document any scope changes that occur after."
        ),
        roi_formula=(
            "ROI % = (cumulative measured savings - implementation cost) / implementation cost x 100, "
            "where savings = (baseline monthly run cost - actual monthly run cost) summed since go-live."
        ),
        measurement_cadence="monthly",
        measurement_duration="12 months post go-live",
        assumptions=[
            "Affected scope is stable enough for baseline comparison",
            "Cost and ticket data remain available at the same granularity",
        ],
        measurement_risks=[
            "Attribution: other initiatives may move the same KPIs",
            "Baseline drift if scope grows or shrinks after go-live",
        ],
        unmeasurable_claims=[],
    )


def generate_roi_plan(
    title: str,
    description: str,
    estimated_cost: Optional[float],
    opportunity_context: Optional[dict] = None,
) -> dict:
    """Returns {'plan': ROIPlan-as-dict, 'generated_by': 'claude'|'template', 'note': ...}."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        plan = _template_plan(title, description, estimated_cost)
        return {
            "plan": plan.model_dump(),
            "generated_by": "template",
            "note": "ANTHROPIC_API_KEY not set — returned a generic template plan.",
        }

    import anthropic

    cost_line = f"\nEstimated implementation cost: ${estimated_cost:,.0f}" if estimated_cost else ""
    opp_block = ""
    if opportunity_context:
        opp_block = (
            "\n\nThis business case addresses an opportunity detected from the customer's "
            "own data — anchor the baseline and KPIs to it:\n"
            f"- Opportunity: {opportunity_context.get('title')}\n"
            f"- Category: {opportunity_context.get('category')} "
            f"(source system: {opportunity_context.get('source')})\n"
            f"- Detected estimated annual savings: "
            f"${opportunity_context.get('estimated_annual_savings', 0):,.0f}\n"
            f"- Detection logic: {opportunity_context.get('description')}"
        )
    user_message = (
        f"Business case title: {title}\n"
        f"Business case description:\n{description}{cost_line}{opp_block}\n\n"
        "Digest this business case and produce the ROI measurement plan."
    )

    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            output_format=ROIPlan,
        )
        plan: ROIPlan = response.parsed_output
        return {"plan": plan.model_dump(), "generated_by": "claude", "note": None}
    except Exception as exc:  # keep the product usable if the API call fails
        plan = _template_plan(title, description, estimated_cost)
        return {
            "plan": plan.model_dump(),
            "generated_by": "template",
            "note": f"Claude API call failed ({type(exc).__name__}); returned template plan.",
        }
