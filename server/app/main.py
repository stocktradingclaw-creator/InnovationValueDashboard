"""InnovationValueDashboard API.

Run with:  uvicorn app.main:app --reload --port 8000  (from the server/ directory)
"""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import (
    calibration, connectors, db, demo, hub, metrics, opportunities,
    portfolio, prioritization, roi, timeline,
)
from .ingestion import SOURCE_TYPES, IngestionError, normalize_rows, parse_csv

app = FastAPI(title="InnovationValueDashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def _loaded_datasets() -> Dict[str, List[Dict[str, Any]]]:
    return {
        st: normalize_rows(st, db.load_dataset(st))
        for st in SOURCE_TYPES
        if db.load_dataset(st)
    }


def _analyze() -> List[Dict[str, Any]]:
    return opportunities.analyze(_loaded_datasets())


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


# -------------------------------------------------------------------- datasets

@app.get("/api/datasets")
def list_datasets() -> Dict[str, Any]:
    meta = db.dataset_meta()
    return {
        "sources": [
            {
                "source_type": st,
                "label": spec["label"],
                "required_columns": spec["required"],
                "rows_loaded": meta.get(st, {}).get("rows_loaded", 0),
                "origin": meta.get(st, {}).get("origin"),
                "updated_at": meta.get(st, {}).get("updated_at"),
            }
            for st, spec in SOURCE_TYPES.items()
        ]
    }


@app.post("/api/datasets/load-samples")
def load_samples() -> Dict[str, Any]:
    loaded = {}
    for source_type in SOURCE_TYPES:
        path = SAMPLE_DIR / f"{source_type}.csv"
        if not path.exists():
            raise HTTPException(500, f"Sample file missing: {path.name}")
        rows = parse_csv(source_type, path.read_bytes())
        db.save_dataset(source_type, rows, origin="sample")
        loaded[source_type] = len(rows)
    return {"loaded": loaded}


@app.post("/api/datasets/{source_type}")
async def upload_dataset(source_type: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    try:
        rows = parse_csv(source_type, raw)
    except IngestionError as exc:
        raise HTTPException(400, str(exc))
    db.save_dataset(source_type, rows, origin="csv")
    return {"source_type": source_type, "rows_loaded": len(rows)}


@app.delete("/api/datasets/{source_type}")
def clear_dataset(source_type: str) -> Dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise HTTPException(404, f"Unknown source type '{source_type}'")
    db.delete_dataset(source_type)
    return {"source_type": source_type, "rows_loaded": 0}


# ------------------------------------------------------------------ connectors

class ServiceNowSyncRequest(BaseModel):
    instance_url: str
    username: str
    password: str
    source: str  # 'cmdb' | 'itsm'
    table: Optional[str] = None
    field_map: Optional[Dict[str, str]] = None
    limit: int = 10000


@app.post("/api/connectors/servicenow/sync")
def servicenow_sync(body: ServiceNowSyncRequest) -> Dict[str, Any]:
    if body.source not in ("cmdb", "itsm"):
        raise HTTPException(400, "source must be 'cmdb' or 'itsm'")
    try:
        rows = connectors.sync_servicenow(
            body.instance_url, body.username, body.password,
            body.source, body.field_map, body.table, body.limit,
        )
    except connectors.ConnectorError as exc:
        raise HTTPException(502, str(exc))
    if not rows:
        raise HTTPException(400, "ServiceNow returned no records — check table and filters")
    db.save_dataset(body.source, rows, origin="servicenow")
    return {"source_type": body.source, "rows_loaded": len(rows), "origin": "servicenow"}


class SapSyncRequest(BaseModel):
    service_url: str
    entity_set: str
    username: Optional[str] = None
    password: Optional[str] = None
    field_map: Optional[Dict[str, str]] = None
    limit: int = 10000


@app.post("/api/connectors/sap/sync")
def sap_sync(body: SapSyncRequest) -> Dict[str, Any]:
    try:
        rows = connectors.sync_sap_odata(
            body.service_url, body.entity_set, body.username,
            body.password, body.field_map, body.limit,
        )
    except connectors.ConnectorError as exc:
        raise HTTPException(502, str(exc))
    if not rows:
        raise HTTPException(400, "SAP service returned no records — check the entity set")
    db.save_dataset("erp", rows, origin="sap_odata")
    return {"source_type": "erp", "rows_loaded": len(rows), "origin": "sap_odata"}


# --------------------------------------------------------------- opportunities

@app.get("/api/opportunities")
def get_opportunities(
    value_weight: Optional[float] = Query(None, description="Weight for size of prize"),
    efficiency_weight: Optional[float] = Query(None, description="Weight for payback ratio"),
    speed_weight: Optional[float] = Query(None, description="Weight for time to value"),
    simplicity_weight: Optional[float] = Query(None, description="Weight for low complexity"),
) -> Dict[str, Any]:
    try:
        if all(w is None for w in (value_weight, efficiency_weight, speed_weight, simplicity_weight)):
            weights = hub.get_scoring_config()["opportunity_weights"]
        else:
            weights = prioritization.normalize_weights(
                value_weight, efficiency_weight, speed_weight, simplicity_weight
            )
    except prioritization.WeightError as exc:
        raise HTTPException(400, str(exc))

    result = prioritization.prioritize(_analyze(), weights, calibration.factors())
    return {
        "opportunities": result["opportunities"],
        "total_estimated_annual_savings": round(
            sum(o["estimated_annual_savings"] for o in result["opportunities"]), 2
        ),
        "prioritization": {
            "weights": result["weights"],
            "summary": result["summary"],
        },
    }


# -------------------------------------------------------------- business cases

class BusinessCaseRequest(BaseModel):
    title: str
    description: str
    estimated_cost: Optional[float] = None
    linked_opportunity_id: Optional[str] = None


@app.post("/api/business-cases")
def create_business_case(body: BusinessCaseRequest) -> Dict[str, Any]:
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "title and description are required")

    linked_opportunity = None
    if body.linked_opportunity_id:
        match = next(
            (o for o in _analyze() if o["id"] == body.linked_opportunity_id), None
        )
        if match is None:
            raise HTTPException(
                400,
                f"Opportunity '{body.linked_opportunity_id}' not found in the current analysis",
            )
        # snapshot the essentials so the link survives data changes
        linked_opportunity = {
            k: match[k]
            for k in ("id", "title", "category", "source", "estimated_annual_savings", "description")
        }

    result = roi.generate_roi_plan(
        body.title.strip(), body.description.strip(), body.estimated_cost,
        opportunity_context=linked_opportunity,
    )
    case = db.create_business_case(
        title=body.title.strip(),
        description=body.description.strip(),
        estimated_cost=body.estimated_cost,
        roi_plan=result["plan"],
        generated_by=result["generated_by"],
        note=result["note"],
        linked_opportunity=linked_opportunity,
    )

    # Linked opportunities ship their own measure: freeze the baseline now so
    # post-implementation evidence is computed by the same query, not typed in.
    if body.linked_opportunity_id:
        match = next(
            (o for o in _analyze() if o["id"] == body.linked_opportunity_id), None
        )
        measure = (match or {}).get("measure")
        if measure:
            definition = {k: v for k, v in measure.items() if k != "label"}
            baseline = metrics.compute(definition, _loaded_datasets())
            case = db.create_metric_binding(
                case_id=case["id"],
                label=measure["label"],
                kpi_name=None,
                definition=definition,
                unit=metrics.unit_for(definition),
                baseline_value=baseline["value"],
                baseline_rows=baseline["rows_matched"],
            )
    return case


@app.get("/api/business-cases")
def list_business_cases() -> Dict[str, Any]:
    return {"business_cases": db.list_business_cases()}


class ImplementRequest(BaseModel):
    go_live_date: datetime.date


@app.post("/api/business-cases/{case_id}/implement")
def implement_case(case_id: str, body: ImplementRequest) -> Dict[str, Any]:
    case = db.mark_implemented(case_id, body.go_live_date.isoformat())
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    return case


class ReadingRequest(BaseModel):
    kpi_name: str
    reading_date: datetime.date
    value: float
    note: Optional[str] = None


@app.post("/api/business-cases/{case_id}/readings")
def add_reading(case_id: str, body: ReadingRequest) -> Dict[str, Any]:
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    kpi_names = {k["name"] for k in case["roi_plan"].get("kpis", [])}
    if body.kpi_name not in kpi_names:
        raise HTTPException(400, f"'{body.kpi_name}' is not a KPI in this case's ROI plan")
    return db.add_kpi_reading(
        case_id, body.kpi_name, body.reading_date.isoformat(), body.value, body.note
    )


class BindingRequest(BaseModel):
    label: str
    definition: Dict[str, Any]
    kpi_name: Optional[str] = None


@app.post("/api/business-cases/{case_id}/bindings")
def add_binding(case_id: str, body: BindingRequest) -> Dict[str, Any]:
    try:
        metrics.validate_definition(body.definition)
    except metrics.MetricError as exc:
        raise HTTPException(400, str(exc))
    baseline = metrics.compute(body.definition, _loaded_datasets())
    case = db.create_metric_binding(
        case_id=case_id,
        label=body.label.strip(),
        kpi_name=body.kpi_name,
        definition=body.definition,
        unit=metrics.unit_for(body.definition),
        baseline_value=baseline["value"],
        baseline_rows=baseline["rows_matched"],
    )
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    return case


@app.post("/api/business-cases/{case_id}/bindings/{binding_id}/observe")
def observe_binding(case_id: str, binding_id: int) -> Dict[str, Any]:
    binding = db.get_binding(case_id, binding_id)
    if binding is None:
        raise HTTPException(404, f"Binding {binding_id} not found on case '{case_id}'")
    observation = metrics.compute(binding["definition"], _loaded_datasets())
    return db.add_metric_observation(
        case_id, binding_id, observation["value"], observation["rows_matched"]
    )


@app.get("/api/calibration")
def get_calibration() -> Dict[str, Any]:
    return calibration.report()


# ------------------------------------------------------------------ ideas & hub

class IdeaRequest(BaseModel):
    title: str
    description: str
    submitter: Optional[str] = None
    category: Optional[str] = None
    estimated_annual_benefit: Optional[float] = None
    benefit_type: Optional[str] = None
    horizon: Optional[str] = None
    challenge_id: Optional[str] = None
    beneficiary: Optional[str] = None
    pain_point: Optional[str] = None
    initiative_id: Optional[str] = None


def _prioritized_opps() -> List[Dict[str, Any]]:
    weights = hub.get_scoring_config()["opportunity_weights"]
    return prioritization.prioritize(_analyze(), weights, calibration.factors())["opportunities"]


def _ingest_idea(body: IdeaRequest, source: str,
                 submitted_at: Optional[str] = None) -> Dict[str, Any]:
    if body.benefit_type and body.benefit_type not in hub.BENEFIT_TYPES:
        raise HTTPException(400, f"benefit_type must be one of {hub.BENEFIT_TYPES}")
    if body.horizon and body.horizon not in ("h1", "h2", "h3"):
        raise HTTPException(400, "horizon must be h1, h2, or h3")
    challenge = db.get_challenge(body.challenge_id) if body.challenge_id else None
    if body.challenge_id and challenge is None:
        raise HTTPException(400, f"Challenge '{body.challenge_id}' not found")
    initiative = db.get_initiative(body.initiative_id) if body.initiative_id else None
    if body.initiative_id and initiative is None:
        raise HTTPException(400, f"Initiative '{body.initiative_id}' not found")
    opps = _prioritized_opps()
    assessment = hub.triage_idea(
        body.title, body.description, opps,
        category=body.category, estimated_annual_benefit=body.estimated_annual_benefit,
        benefit_type=body.benefit_type, horizon=body.horizon, challenge=challenge,
        initiative=initiative, existing_ideas=db.list_ideas(),
        beneficiary=body.beneficiary, pain_point=body.pain_point,
    )
    idea = db.create_idea(
        body.title.strip(), body.description.strip(),
        (body.submitter or "").strip() or None, assessment,
        category=(body.category or "").strip() or assessment.get("derived_category"),
        estimated_annual_benefit=body.estimated_annual_benefit,
        source=source, submitted_at=submitted_at,
        benefit_type=assessment.get("benefit_type"),
        horizon=assessment.get("horizon"),
        challenge_id=body.challenge_id,
        beneficiary=(body.beneficiary or "").strip() or None,
        pain_point=(body.pain_point or "").strip() or None,
        initiative_id=body.initiative_id,
    )
    db.log_automation(
        "idea_triage", assessment["recommendation"], idea["id"],
        assessment["rationale"][:200],
    )
    return idea


@app.post("/api/ideas")
def submit_idea(body: IdeaRequest) -> Dict[str, Any]:
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "title and description are required")
    return _ingest_idea(body, source="manual")


@app.post("/api/ideas/import")
async def import_ideas(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Bulk-ingest a client's existing idea backlog. Expected columns:
    title, description; optional: submitter, category, estimated_annual_benefit,
    submitted_at. Every row is triaged, scored, and enriched on the way in."""
    import csv as csv_module
    import io

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 encoded CSV")
    reader = csv_module.DictReader(io.StringIO(text))
    headers = {(h or "").strip().lower() for h in (reader.fieldnames or [])}
    if not {"title", "description"} <= headers:
        raise HTTPException(400, "CSV needs at least 'title' and 'description' columns")

    imported, skipped = [], 0
    for row in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("title") or not row.get("description"):
            skipped += 1
            continue
        benefit = None
        if row.get("estimated_annual_benefit"):
            try:
                benefit = float(row["estimated_annual_benefit"].replace("$", "").replace(",", ""))
            except ValueError:
                benefit = None
        idea = _ingest_idea(
            IdeaRequest(
                title=row["title"], description=row["description"],
                submitter=row.get("submitter") or None,
                category=row.get("category") or None,
                estimated_annual_benefit=benefit,
                beneficiary=row.get("beneficiary") or None,
                pain_point=row.get("pain_point") or None,
            ),
            source="import",
            submitted_at=row.get("submitted_at") or None,
        )
        imported.append(idea["id"])
    return {"imported": len(imported), "skipped": skipped, "ids": imported}


@app.get("/api/ideas")
def list_ideas() -> Dict[str, Any]:
    return {"ideas": db.list_ideas()}


@app.post("/api/ideas/{idea_id}/evaluate")
def evaluate_idea(idea_id: str) -> Dict[str, Any]:
    idea = db.get_idea(idea_id)
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    evaluation = hub.ai_evaluate_idea(idea, _prioritized_opps())
    assessment = dict(idea.get("assessment") or {})
    assessment["ai_evaluation"] = evaluation
    db.log_automation(
        "ai_evaluate", evaluation["suggested_priority"], idea_id,
        evaluation["validation_notes"][:200],
    )
    return db.update_idea_assessment(idea_id, assessment)


def _promote_idea(idea: Dict[str, Any]) -> Dict[str, Any]:
    matched = (idea.get("assessment") or {}).get("matched_opportunity") or {}
    linked_opportunity = None
    if matched.get("id"):
        current = next((o for o in _analyze() if o["id"] == matched["id"]), None)
        if current:
            linked_opportunity = {
                k: current[k]
                for k in ("id", "title", "category", "source",
                          "estimated_annual_savings", "description")
            }

    result = roi.generate_roi_plan(
        idea["title"], idea["description"], None,
        opportunity_context=linked_opportunity,
    )
    case = db.create_business_case(
        title=idea["title"],
        description=idea["description"],
        estimated_cost=None,
        roi_plan=result["plan"],
        generated_by=result["generated_by"],
        note=f"Promoted from idea {idea['id']}"
             + (f" (submitted by {idea['submitter']})" if idea["submitter"] else ""),
        linked_opportunity=linked_opportunity,
        stage="proposed",
        horizon=idea.get("horizon") or "h1",
        initiative_id=idea.get("initiative_id"),
    )
    db.notify(
        idea.get("submitter"), "idea", idea["id"],
        f"Your idea '{idea['title']}' was approved and promoted to business case {case['id']}.",
    )
    if linked_opportunity:
        measure = next(
            (o.get("measure") for o in _analyze() if o["id"] == linked_opportunity["id"]),
            None,
        )
        if measure:
            definition = {k: v for k, v in measure.items() if k != "label"}
            baseline = metrics.compute(definition, _loaded_datasets())
            db.create_metric_binding(
                case_id=case["id"], label=measure["label"], kpi_name=None,
                definition=definition, unit=metrics.unit_for(definition),
                baseline_value=baseline["value"], baseline_rows=baseline["rows_matched"],
            )
            case = db.get_business_case(case["id"])
    db.update_idea(idea["id"], "business_case", case["id"])
    return {"idea": db.get_idea(idea["id"]), "case": case}


@app.post("/api/ideas/{idea_id}/promote")
def promote_idea(idea_id: str) -> Dict[str, Any]:
    idea = db.get_idea(idea_id)
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    if idea["status"] == "business_case":
        raise HTTPException(400, "Idea already has a business case")
    if idea["status"] != "prioritized":
        raise HTTPException(
            400,
            "Business cases are developed for prioritized ideas only — walk the gates: "
            "qualify, then prioritize (Command Center).",
        )
    return _promote_idea(idea)


@app.post("/api/ideas/{idea_id}/decline")
def decline_idea(idea_id: str) -> Dict[str, Any]:
    idea = db.update_idea(idea_id, "declined")
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    return idea


# ------------------------------------------------- scoring framework & governance

@app.get("/api/scoring-config")
def get_scoring_config() -> Dict[str, Any]:
    return hub.get_scoring_config()


def _require_admin(authorization: Optional[str]) -> None:
    """Optional hardening: when IVD_ADMIN_TOKEN is set, configuration changes
    require it as a bearer token. Off by default for local/demo use."""
    import os
    expected = os.environ.get("IVD_ADMIN_TOKEN")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(401, "Configuration changes require the admin token")


@app.put("/api/scoring-config")
def put_scoring_config(body: Dict[str, Any], authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    _require_admin(authorization)
    try:
        return hub.save_scoring_config(body)
    except hub.ConfigError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/governance")
def get_governance() -> Dict[str, Any]:
    return {"areas": hub.GOVERNANCE_AREAS, "assignments": hub.get_governance()}


@app.put("/api/governance")
def put_governance(body: Dict[str, List[str]], authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    _require_admin(authorization)
    try:
        return {"areas": hub.GOVERNANCE_AREAS, "assignments": hub.save_governance(body)}
    except hub.ConfigError as exc:
        raise HTTPException(400, str(exc))


# --------------------------------------------------------------- command center

class DecisionRequest(BaseModel):
    subject_type: str  # 'idea' | 'case'
    subject_id: str
    decision: str      # ideas: qualify|prioritize|hold|develop|reject|feedback|approve(alias)
                       # cases: approve|reject|feedback|experiment
    actor: Optional[str] = None
    comment: Optional[str] = None


# stage -> what 'approve' means for an idea (alias for the stage's forward gate)
_IDEA_APPROVE_ALIAS = {"proposed": "qualify", "qualified": "prioritize", "prioritized": "develop"}
_IDEA_GATE_AREA = {
    "qualify": "idea_screening",
    "prioritize": "portfolio_oversight",
    "hold": "portfolio_oversight",
    "develop": "portfolio_oversight",
}


_CASE_APPROVE_NEXT = {
    "draft": "proposed", "proposed": "approved", "experiment": "approved",
    "approved": "in_delivery", "value_realized": "scale",
}


def _governance_area_for(subject_type: str, case: Optional[Dict[str, Any]]) -> str:
    if subject_type == "idea":
        return "idea_screening"
    stage = (case or {}).get("stage", "proposed")
    if stage in ("draft", "proposed", "approved"):
        return "business_case_approval"
    if stage == "in_delivery":
        return "delivery"
    return "value_verification"


@app.get("/api/command/queue")
def command_queue() -> Dict[str, Any]:
    ideas = db.list_ideas()
    cases = db.list_business_cases()

    def _with_checklist(items):
        return [{**i, "gate_checklist": hub.gate_checklist(i)} for i in items]

    return {
        "idea_queues": {
            "screening": _with_checklist([i for i in ideas if i["status"] == "proposed"]),
            "prioritization": _with_checklist([i for i in ideas if i["status"] == "qualified"]),
            "development": _with_checklist([i for i in ideas if i["status"] == "prioritized"]),
            "backlog": [i for i in ideas if i["status"] == "backlog"],
        },
        "cases_pending_approval": [c for c in cases if c["stage"] in ("draft", "proposed")],
        "cases_in_experiment": [c for c in cases if c["stage"] == "experiment"],
        "cases_in_motion": [c for c in cases if c["stage"] in ("approved", "in_delivery")],
        "history": db.workflow_events(30),
        "governance": hub.get_governance(),
    }


@app.post("/api/command/decide")
def command_decide(body: DecisionRequest) -> Dict[str, Any]:
    if body.subject_type not in ("idea", "case"):
        raise HTTPException(400, "subject_type must be 'idea' or 'case'")
    valid = ("approve", "reject", "feedback", "experiment", "qualify", "prioritize", "hold", "develop")
    if body.decision not in valid:
        raise HTTPException(400, f"decision must be one of {valid}")

    if body.subject_type == "idea":
        idea = db.get_idea(body.subject_id)
        if idea is None:
            raise HTTPException(404, f"Idea '{body.subject_id}' not found")
        decision = body.decision
        if decision == "experiment":
            raise HTTPException(400, "experiment applies to cases, not ideas")
        if decision == "approve":  # alias: advance through the current stage's gate
            decision = _IDEA_APPROVE_ALIAS.get(idea["status"])
            if decision is None:
                raise HTTPException(400, f"No forward gate from status '{idea['status']}'")

        area = _IDEA_GATE_AREA.get(decision, "idea_screening")
        blocked = hub.check_authority(area, body.actor)
        if blocked:
            raise HTTPException(403, blocked)
        db.add_workflow_event("idea", body.subject_id, decision, body.actor, body.comment)

        if decision == "qualify":
            if idea["status"] != "proposed":
                raise HTTPException(400, f"Only proposed ideas pass the qualification gate (status: {idea['status']})")
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"Your idea '{idea['title']}' passed the qualification gate and moves to portfolio prioritization.")
            return {"result": db.update_idea(body.subject_id, "qualified")}
        if decision == "prioritize":
            if idea["status"] != "qualified":
                raise HTTPException(400, f"Only qualified ideas can be prioritized (status: {idea['status']})")
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"'{idea['title']}' was prioritized into the portfolio — an AI business case is next.")
            return {"result": db.update_idea(body.subject_id, "prioritized")}
        if decision == "hold":
            if idea["status"] not in ("qualified", "prioritized"):
                raise HTTPException(400, "Only qualified/prioritized ideas can be held")
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"'{idea['title']}' is on the backlog — qualified, awaiting portfolio capacity.")
            return {"result": db.update_idea(body.subject_id, "backlog")}
        if decision == "develop":
            if idea["status"] != "prioritized":
                raise HTTPException(400, "Business cases are developed for prioritized ideas only")
            return {"result": _promote_idea(idea)}
        if decision == "reject":
            db.notify(
                idea.get("submitter"), "idea", idea["id"],
                f"Your idea '{idea['title']}' was not taken forward."
                + (f" Feedback: {body.comment}" if body.comment else ""),
            )
            return {"result": db.update_idea(body.subject_id, "declined")}
        db.notify(
            idea.get("submitter"), "idea", idea["id"],
            f"Feedback on your idea '{idea['title']}': {body.comment or '(no comment)'}",
        )
        return {"result": idea}

    case = db.get_business_case(body.subject_id)
    if case is None:
        raise HTTPException(404, f"Business case '{body.subject_id}' not found")
    area = _governance_area_for("case", case)
    blocked = hub.check_authority(area, body.actor)
    if blocked:
        raise HTTPException(403, blocked)
    db.add_workflow_event("case", body.subject_id, body.decision, body.actor, body.comment)
    submitter = db.submitter_for_case(body.subject_id)
    if body.decision == "experiment":
        if case["stage"] not in ("draft", "proposed"):
            raise HTTPException(400, "only draft/proposed cases can be sent to experiment")
        db.notify(submitter, "case", case["id"],
                  f"'{case['title']}' is being validated with an experiment before full approval.")
        return {"result": db.set_stage(body.subject_id, "experiment")}
    if body.decision == "approve":
        next_stage = _CASE_APPROVE_NEXT.get(case["stage"])
        if next_stage is None:
            raise HTTPException(
                400, f"Cases in stage '{case['stage']}' advance via /implement or automation"
            )
        if case["stage"] == "approved" and case["funding"]["released"] <= 0:
            raise HTTPException(
                400,
                "Funding gate: release a funding tranche before mobilizing into delivery "
                "(plan and release tranches on this case).",
            )
        db.notify(submitter, "case", case["id"],
                  f"'{case['title']}' advanced to {next_stage.replace('_', ' ')}.")
        return {"result": db.set_stage(body.subject_id, next_stage)}
    if body.decision == "reject":
        db.notify(submitter, "case", case["id"],
                  f"'{case['title']}' was closed."
                  + (f" Reason: {body.comment}" if body.comment else ""))
        return {"result": db.set_stage(body.subject_id, "closed")}
    return {"result": case}


class StageRequest(BaseModel):
    stage: str


@app.post("/api/business-cases/{case_id}/stage")
def set_case_stage(case_id: str, body: StageRequest) -> Dict[str, Any]:
    if body.stage not in db.STAGES:
        raise HTTPException(400, f"stage must be one of {db.STAGES}")
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    if body.stage == "live":
        raise HTTPException(400, "use /implement to go live — it requires a go-live date")
    if body.stage in ("value_realized", "scale") and case["status"] != "implemented":
        raise HTTPException(400, "case must be implemented before value_realized/scale")
    return db.set_stage(case_id, body.stage)


# ------------------------------------------------------ strategic initiatives

class InitiativeRequest(BaseModel):
    name: str
    objective: str


@app.post("/api/initiatives")
def create_initiative(body: InitiativeRequest) -> Dict[str, Any]:
    if not body.name.strip() or not body.objective.strip():
        raise HTTPException(400, "name and objective are required")
    return db.create_initiative(body.name.strip(), body.objective.strip())


@app.get("/api/initiatives")
def list_initiatives() -> Dict[str, Any]:
    """Initiatives with value rollups: ideas -> cases -> forecast -> verified."""
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    rollups = []
    for initiative in db.list_initiatives():
        tagged_ideas = [i for i in ideas if i.get("initiative_id") == initiative["id"]]
        tagged_cases = [c for c in cases if c.get("initiative_id") == initiative["id"]]
        rollups.append({
            **initiative,
            "ideas_count": len(tagged_ideas),
            "cases_count": len(tagged_cases),
            "estimated_idea_benefit": round(sum(
                i.get("estimated_annual_benefit") or
                (i.get("assessment") or {}).get("estimated_annual_benefit") or 0
                for i in tagged_ideas), 2),
            "forecast_annual_savings": round(sum(
                (c["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
                for c in tagged_cases), 2),
            "verified_annual_savings": round(sum(
                (c["tracking"] or {}).get("measured_annual_savings") or 0
                for c in tagged_cases), 2),
        })
    return {"initiatives": rollups}


# ------------------------------------------------------------------ demo studio

class DemoRequest(BaseModel):
    client: Optional[str] = None
    industry: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/demo/generate")
def demo_generate(body: DemoRequest) -> Dict[str, Any]:
    client = (body.client or "").strip()
    industry = (body.industry or "").strip()
    if not client and not industry:
        raise HTTPException(400, "provide a client name, an industry, or both")
    try:
        demo.snapshot()  # baseline first — revert restores this exact state
    except demo.DemoError as exc:
        raise HTTPException(400, str(exc))

    portfolio_spec = demo.build_portfolio(industry or None, client or None, body.notes)
    label = client or f"{industry.title()} prospect"
    initiative_ids = [
        db.create_initiative(i["name"], i["objective"])["id"]
        for i in portfolio_spec["initiatives"]
    ]
    created = 0
    for spec in portfolio_spec["ideas"]:
        index = spec.get("initiative_index") or 0
        initiative_id = initiative_ids[index] if 0 <= index < len(initiative_ids) else None
        benefit_type = spec.get("benefit_type")
        if benefit_type not in hub.BENEFIT_TYPES:
            benefit_type = "cost_reduction"
        _ingest_idea(
            IdeaRequest(
                title=spec["title"], description=spec["description"],
                submitter=f"{label} workshop",
                category=spec.get("category"),
                estimated_annual_benefit=spec.get("estimated_annual_benefit"),
                benefit_type=benefit_type,
                beneficiary=spec.get("beneficiary"), pain_point=spec.get("pain_point"),
                initiative_id=initiative_id,
            ),
            source="demo",
        )
        created += 1
    # walk the first ideas through the early gates so the stage-gate pipeline
    # presents with life in it (no AI spend — cases stay ungenerated)
    generated = [i for i in db.list_ideas() if i["source"] == "demo"]
    for idea in generated[:3]:
        db.update_idea(idea["id"], "qualified")
        db.add_workflow_event("idea", idea["id"], "qualify", "demo studio", "seeded by demo studio")
    for idea in generated[:1]:
        db.update_idea(idea["id"], "prioritized")
        db.add_workflow_event("idea", idea["id"], "prioritize", "demo studio", "seeded by demo studio")

    info = demo.mark_active(
        label, industry or "inferred from client strategy",
        portfolio_spec["generated_by"], len(initiative_ids), created,
    )
    return {"demo": info}


@app.get("/api/demo/status")
def demo_status() -> Dict[str, Any]:
    return {"demo": demo.status(), "industries": demo.INDUSTRIES}


@app.post("/api/demo/revert")
def demo_revert() -> Dict[str, Any]:
    try:
        info = demo.revert()
    except demo.DemoError as exc:
        raise HTTPException(400, str(exc))
    return {"reverted": info}


# ------------------------------------------------------------------ challenges

class ChallengeRequest(BaseModel):
    title: str
    question: str
    theme: Optional[str] = None
    closes_at: Optional[str] = None


@app.post("/api/challenges")
def create_challenge(body: ChallengeRequest) -> Dict[str, Any]:
    if not body.title.strip() or not body.question.strip():
        raise HTTPException(400, "title and question are required")
    return db.create_challenge(
        body.title.strip(), body.question.strip(), body.theme, body.closes_at
    )


@app.get("/api/challenges")
def list_challenges() -> Dict[str, Any]:
    return {"challenges": db.list_challenges()}


@app.post("/api/challenges/{challenge_id}/close")
def close_challenge(challenge_id: str) -> Dict[str, Any]:
    challenge = db.close_challenge(challenge_id)
    if challenge is None:
        raise HTTPException(404, f"Challenge '{challenge_id}' not found")
    return challenge


# ----------------------------------------------------------------- experiments

class ExperimentRequest(BaseModel):
    hypothesis: str
    method: str
    success_criteria: str
    cost: Optional[float] = None


@app.post("/api/business-cases/{case_id}/experiments")
def add_experiment(case_id: str, body: ExperimentRequest) -> Dict[str, Any]:
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    if case["stage"] not in ("draft", "proposed", "experiment"):
        raise HTTPException(400, "experiments belong before approval (draft/proposed/experiment)")
    result = db.add_experiment(
        case_id, body.hypothesis.strip(), body.method.strip(),
        body.success_criteria.strip(), body.cost,
    )
    if case["stage"] != "experiment":
        result = db.set_stage(case_id, "experiment")
    return result


class ConcludeExperimentRequest(BaseModel):
    outcome: str  # 'proceed' | 'kill' | 'pivot'
    learnings: str


@app.post("/api/business-cases/{case_id}/experiments/{experiment_id}/conclude")
def conclude_experiment(case_id: str, experiment_id: int,
                        body: ConcludeExperimentRequest) -> Dict[str, Any]:
    if body.outcome not in ("proceed", "kill", "pivot"):
        raise HTTPException(400, "outcome must be 'proceed', 'kill', or 'pivot'")
    if not body.learnings.strip():
        raise HTTPException(400, "learnings are required — kills without learning are waste")
    case = db.conclude_experiment(case_id, experiment_id, body.outcome, body.learnings.strip())
    if case is None:
        raise HTTPException(404, f"Open experiment {experiment_id} not found on '{case_id}'")
    submitter = db.submitter_for_case(case_id)
    if body.outcome == "kill":
        case = db.set_stage(case_id, "closed")
        db.log_automation("experiment", "killed", case_id,
                          f"experiment {experiment_id}: {body.learnings[:150]}")
        db.notify(submitter, "case", case_id,
                  f"Thank you — the experiment on '{case['title']}' saved us from a bigger miss. "
                  f"What we learned: {body.learnings[:150]} This learning is now in the library "
                  "for the next team.")
    else:
        db.notify(submitter, "case", case_id,
                  f"Experiment on '{case['title']}' concluded: {body.outcome}.")
    return case


# ------------------------------------------------------------- funding tranches

class TrancheRequest(BaseModel):
    label: str
    amount: float
    milestone: str


@app.post("/api/business-cases/{case_id}/tranches")
def add_tranche(case_id: str, body: TrancheRequest) -> Dict[str, Any]:
    if body.amount <= 0:
        raise HTTPException(400, "amount must be > 0")
    case = db.add_tranche(case_id, body.label.strip(), body.amount, body.milestone.strip())
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    return case


class ReleaseRequest(BaseModel):
    actor: Optional[str] = None


@app.post("/api/business-cases/{case_id}/tranches/{tranche_id}/release")
def release_tranche(case_id: str, tranche_id: int, body: ReleaseRequest) -> Dict[str, Any]:
    blocked = hub.check_authority("business_case_approval", body.actor)
    if blocked:
        raise HTTPException(403, blocked)
    case = db.release_tranche(case_id, tranche_id, body.actor)
    if case is None:
        raise HTTPException(404, f"Planned tranche {tranche_id} not found on '{case_id}'")
    db.add_workflow_event("case", case_id, "tranche_released", body.actor,
                          f"tranche {tranche_id}")
    return case


# --------------------------------------------------------------- notifications

@app.get("/api/notifications")
def get_notifications(recipient: str = Query(...)) -> Dict[str, Any]:
    return {"notifications": db.notifications_for(recipient)}


def _rescore_idea(idea_id: str) -> Dict[str, Any]:
    """Re-run triage with stored intake fields plus current social signal so
    peer recognition (votes, build-ons) moves the desirability score. The AI
    evaluation, if present, is preserved."""
    idea = db.get_idea(idea_id)
    challenge = db.get_challenge(idea["challenge_id"]) if idea.get("challenge_id") else None
    initiative = db.get_initiative(idea["initiative_id"]) if idea.get("initiative_id") else None
    others = [i for i in db.list_ideas() if i["id"] != idea_id]
    fresh = hub.triage_idea(
        idea["title"], idea["description"], _prioritized_opps(),
        category=idea.get("category"),
        estimated_annual_benefit=idea.get("estimated_annual_benefit"),
        benefit_type=idea.get("benefit_type"), horizon=idea.get("horizon"),
        challenge=challenge, initiative=initiative, existing_ideas=others,
        beneficiary=idea.get("beneficiary"), pain_point=idea.get("pain_point"),
        votes=idea.get("vote_count", 0),
        build_ons=sum(1 for c in idea.get("comments", []) if c["build_on"]),
    )
    old = idea.get("assessment") or {}
    if "ai_evaluation" in old:
        fresh["ai_evaluation"] = old["ai_evaluation"]
    return db.update_idea_assessment(idea_id, fresh)


class CommentRequest(BaseModel):
    author: str
    comment: str
    build_on: bool = False


@app.post("/api/ideas/{idea_id}/comments")
def add_comment(idea_id: str, body: CommentRequest) -> Dict[str, Any]:
    if not body.author.strip() or not body.comment.strip():
        raise HTTPException(400, "author and comment are required")
    idea = db.add_comment(idea_id, body.author.strip(), body.comment.strip(), body.build_on)
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    if idea.get("submitter") and idea["submitter"].lower() != body.author.strip().lower():
        db.notify(
            idea["submitter"], "idea", idea_id,
            (f"{body.author} built on your idea '{idea['title']}': {body.comment[:120]}"
             if body.build_on else
             f"{body.author} commented on your idea '{idea['title']}': {body.comment[:120]}"),
        )
    return _rescore_idea(idea_id)


class VoteRequest(BaseModel):
    voter: str


@app.post("/api/ideas/{idea_id}/vote")
def vote_idea(idea_id: str, body: VoteRequest) -> Dict[str, Any]:
    if not body.voter.strip():
        raise HTTPException(400, "voter is required")
    idea = db.add_vote(idea_id, body.voter)
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    return _rescore_idea(idea_id)


@app.get("/api/learnings")
def get_learnings() -> Dict[str, Any]:
    """The learning library — what experiments taught us, kills included.
    Kills are tuition, not failure."""
    return {"learnings": db.learnings()}


# ------------------------------------------------------------- pattern library

@app.get("/api/patterns")
def list_patterns() -> Dict[str, Any]:
    """Proven wins (value realized or scaling) exposed as reusable patterns."""
    patterns = []
    for c in db.list_business_cases():
        if c["stage"] in ("value_realized", "scale"):
            experience_readings = [
                {"kpi": r["kpi_name"], "value": r["value"], "date": r["reading_date"]}
                for r in c["kpi_readings"]
            ][-3:]
            patterns.append({
                "case_id": c["id"],
                "title": c["title"].replace("[Auto-draft] ", ""),
                "category": (c["linked_opportunity"] or {}).get("category"),
                "horizon": c.get("horizon"),
                "forecast_annual_savings": (c["linked_opportunity"] or {}).get(
                    "estimated_annual_savings"),
                "measured_annual_savings": (c["tracking"] or {}).get("measured_annual_savings"),
                "summary": c["roi_plan"].get("summary", ""),
                "stage": c["stage"],
                # the story: problem -> what we tried -> what we learned -> proof
                "story": {
                    "problem": c["description"],
                    "what_we_tried": [
                        {"hypothesis": e["hypothesis"], "outcome": e["outcome"],
                         "learnings": e["learnings"]}
                        for e in c["experiments"] if e["concluded_at"]
                    ],
                    "human_evidence": experience_readings,
                    "credited_to": db.submitter_for_case(c["id"]),
                },
            })
    return {"patterns": patterns}


class ReplicateRequest(BaseModel):
    title: Optional[str] = None


@app.post("/api/patterns/{case_id}/replicate")
def replicate_pattern(case_id: str, body: ReplicateRequest) -> Dict[str, Any]:
    source = db.get_business_case(case_id)
    if source is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    if source["stage"] not in ("value_realized", "scale"):
        raise HTTPException(400, "only proven cases (value_realized/scale) can be replicated")
    clone = db.create_business_case(
        title=body.title or f"Replicate: {source['title'].replace('[Auto-draft] ', '')}",
        description=f"Replicated from proven case {source['id']}. {source['description']}",
        estimated_cost=source["estimated_cost"],
        roi_plan=source["roi_plan"],
        generated_by="pattern",
        note=f"Pattern replication of {source['id']} — verified "
             f"${(source['tracking'] or {}).get('measured_annual_savings', 0):,.0f}/yr at origin.",
        linked_opportunity=source["linked_opportunity"],
        stage="draft",
        horizon=source.get("horizon") or "h1",
    )
    db.add_workflow_event("case", clone["id"], "replicated", None, f"from {source['id']}")
    return clone


@app.get("/api/pipeline")
def pipeline() -> Dict[str, Any]:
    return hub.build_pipeline(db.list_ideas(), db.list_business_cases())


@app.get("/api/lifecycle")
def lifecycle() -> Dict[str, Any]:
    """The stage-gate model with live counts, plus the portfolio register
    (impact vs readiness) for qualified/prioritized ideas."""
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    idea_counts = {stage: 0 for stage in hub.IDEA_STAGES}
    for i in ideas:
        if i["status"] in idea_counts:
            idea_counts[i["status"]] += 1
    case_counts = {stage: 0 for stage in db.STAGES}
    for c in cases:
        case_counts[c["stage"]] = case_counts.get(c["stage"], 0) + 1

    register = []
    for i in ideas:
        if i["status"] not in ("qualified", "prioritized"):
            continue
        a = i.get("assessment") or {}
        components = a.get("score_components") or {}
        register.append({
            "id": i["id"],
            "title": i["title"],
            "status": i["status"],
            "impact": a.get("estimated_annual_benefit")
                      or i.get("estimated_annual_benefit") or 0,
            "readiness": round(
                (components.get("data_grounding", 0) + components.get("completeness", 0)) / 2, 3),
            "score": a.get("score", 0),
            "votes": i.get("vote_count", 0),
        })

    return {
        "spec": hub.LIFECYCLE_SPEC,
        "idea_counts": idea_counts,
        "idea_terminal": {
            "backlog": sum(1 for i in ideas if i["status"] == "backlog"),
            "declined": sum(1 for i in ideas if i["status"] == "declined"),
        },
        "case_counts": case_counts,
        "register": register,
    }


@app.post("/api/automation/run")
def run_automation() -> Dict[str, Any]:
    summary = hub.run_automation(_prioritized_opps(), _loaded_datasets(), db.dataset_meta())
    return {"summary": summary, "recent": db.automation_log_entries(10)}


@app.get("/api/automation")
def automation_status() -> Dict[str, Any]:
    return {
        "last_run": db.meta_get("automation_last_run"),
        "recent": db.automation_log_entries(50),
    }


@app.get("/api/portfolio/diagnostic")
def portfolio_diagnostic() -> Dict[str, Any]:
    rows = normalize_rows("portfolio", db.load_dataset("portfolio"))
    if not rows:
        raise HTTPException(
            400, "No portfolio loaded — upload a PMO export to the 'portfolio' source first"
        )
    return portfolio.diagnose(rows)


def _fmt_money(value: float) -> str:
    return f"${value:,.0f}"


def _headline(funnel: Dict[str, float], ts: Optional[Dict[str, Any]], opps: List[Dict[str, Any]]) -> str:
    if ts and ts["verified_run_rate"] > 0:
        invested = ts["total_invested"]
        run_rate = ts["verified_run_rate"]
        base = (
            f"Innovation investments are returning {_fmt_money(run_rate)}/yr of verified "
            f"savings on {_fmt_money(invested)} invested"
            if invested > 0
            else f"Verified savings are running at {_fmt_money(run_rate)}/yr"
        )
        if ts["break_even_month"]:
            when = ts["break_even_month"]
            qualifier = "projected " if ts["break_even_projected"] else "reached "
            return f"{base}; break-even {qualifier}{when}."
        return f"{base}."
    if funnel["committed_annual_savings"] > 0:
        return (
            f"{_fmt_money(funnel['committed_annual_savings'])}/yr of savings is committed "
            "to business cases; first verified evidence is pending measurement."
        )
    if funnel["identified_annual_savings"] > 0:
        quick = [o for o in opps if o["priority"]["quadrant"] == "quick_win"]
        quick_value = sum(o["estimated_annual_savings"] for o in quick)
        return (
            f"{_fmt_money(funnel['identified_annual_savings'])}/yr of cost-reduction "
            f"opportunity identified — {len(quick)} quick wins worth "
            f"{_fmt_money(quick_value)}/yr are ready for approval."
        )
    return "Connect customer data sources to begin identifying value."


def _decision_queue(
    opps: List[Dict[str, Any]],
    cases: List[Dict[str, Any]],
    portfolio_report: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Frame the dashboard around decisions, not data: what should the
    executive approve, fund, verify, or intervene on — ranked by value."""
    linked_ids = {(c["linked_opportunity"] or {}).get("id") for c in cases}
    decisions: List[Dict[str, Any]] = []

    for o in opps:
        if o["id"] in linked_ids or o["priority"]["quadrant"] != "quick_win":
            continue
        p = o["priority"]
        decisions.append({
            "action": "approve",
            "title": o["title"],
            "detail": (
                f"~{_fmt_money(p['est_implementation_cost'])} to implement · "
                f"payback {p['payback_months']} mo · {o['complexity']} complexity"
            ),
            "annual_value": o["estimated_annual_savings"],
            "nav": "opportunities",
        })
        if sum(1 for d in decisions if d["action"] == "approve") >= 3:
            break

    bet = next(
        (o for o in opps
         if o["id"] not in linked_ids and o["priority"]["quadrant"] == "strategic_bet"),
        None,
    )
    if bet:
        decisions.append({
            "action": "fund",
            "title": f"Develop business case: {bet['title']}",
            "detail": (
                f"largest strategic bet · ~{_fmt_money(bet['priority']['est_implementation_cost'])} "
                f"to implement · {bet['complexity']} complexity"
            ),
            "annual_value": bet["estimated_annual_savings"],
            "nav": "cases",
        })

    for c in cases:
        if c["status"] == "implemented" and not (c["tracking"] or {}).get("measured_annual_savings"):
            forecast = (c["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
            decisions.append({
                "action": "verify",
                "title": f"No verified evidence yet: {c['title']}",
                "detail": "refresh source data and re-observe the metric bindings",
                "annual_value": forecast,
                "nav": "tracking",
            })

    for c in cases:
        if c.get("stage") == "draft":
            forecast = (c["linked_opportunity"] or {}).get("estimated_annual_savings") or 0
            decisions.append({
                "action": "review",
                "title": f"Review auto-drafted case: {c['title'].replace('[Auto-draft] ', '')}",
                "detail": "drafted by the hub with a frozen baseline — confirm cost and promote",
                "annual_value": forecast,
                "nav": "cases",
            })

    if portfolio_report:
        for f in portfolio_report["findings"]:
            if f["severity"] == "high":
                decisions.append({
                    "action": "intervene",
                    "title": f["title"],
                    "detail": f["category"].lower() + " in the existing initiative portfolio",
                    "annual_value": f["value_impact"],
                    "nav": "portfolio",
                })

    decisions.sort(key=lambda d: d["annual_value"], reverse=True)
    return decisions[:6]


@app.get("/api/dashboard")
def dashboard() -> Dict[str, Any]:
    """Everything an executive overview needs, in one call: a plain-English
    headline, the value funnel, a ranked decision queue, trajectory, case
    pipeline, calibration quality, and data freshness."""
    result = prioritization.prioritize(
        _analyze(), hub.get_scoring_config()["opportunity_weights"], calibration.factors()
    )
    opps = result["opportunities"]
    meta = db.dataset_meta()

    # Serverless-friendly automation: the hub runs itself whenever the
    # dashboard is read and the last run is stale. Rules are idempotent.
    if meta and hub.automation_is_stale():
        try:
            hub.run_automation(opps, _loaded_datasets(), meta)
        except Exception:
            pass  # automation must never take the dashboard down

    cases = db.list_business_cases()

    portfolio_rows = db.load_dataset("portfolio")
    portfolio_report = (
        portfolio.diagnose(normalize_rows("portfolio", portfolio_rows))
        if portfolio_rows else None
    )

    identified = sum(o["estimated_annual_savings"] for o in opps)
    risk_adjusted = sum(o["priority"]["risk_adjusted_annual_savings"] for o in opps)
    committed = sum(
        (c["linked_opportunity"] or {}).get("estimated_annual_savings", 0) for c in cases
    )
    measured = sum(
        (c["tracking"] or {}).get("measured_annual_savings", 0) or 0 for c in cases
    )
    claimed = sum(
        (c["tracking"] or {}).get("total_realized_savings", 0) or 0 for c in cases
    )

    quadrants: Dict[str, Dict[str, float]] = {}
    for o in opps:
        q = o["priority"]["quadrant"]
        bucket = quadrants.setdefault(q, {"count": 0, "value": 0.0})
        bucket["count"] += 1
        bucket["value"] += o["estimated_annual_savings"]
    for bucket in quadrants.values():
        bucket["value"] = round(bucket["value"], 2)

    funnel = {
        "identified_annual_savings": round(identified, 2),
        "risk_adjusted_annual_savings": round(risk_adjusted, 2),
        "committed_annual_savings": round(committed, 2),
        "measured_annual_savings": round(measured, 2),
        "claimed_savings_to_date": round(claimed, 2),
    }
    timeline_data = timeline.build(cases)

    return {
        "headline": _headline(funnel, timeline_data["summary"], opps),
        "decisions": _decision_queue(opps, cases, portfolio_report),
        "portfolio_health": portfolio_report["health_score"] if portfolio_report else None,
        "hub": hub.hub_metrics(cases, db.list_ideas()),
        "funnel": funnel,
        "opportunities": {
            "count": len(opps),
            "quadrants": quadrants,
            "top": [
                {
                    "id": o["id"],
                    "title": o["title"],
                    "score": o["priority"]["score"],
                    "estimated_annual_savings": o["estimated_annual_savings"],
                    "quadrant": o["priority"]["quadrant"],
                    "complexity": o["complexity"],
                }
                for o in opps[:5]
            ],
            "count_for_80_pct_of_value": (result["summary"] or {}).get(
                "count_for_80_pct_of_value", 0
            ),
        },
        "pipeline": [
            {
                "id": c["id"],
                "title": c["title"],
                "status": c["status"],
                "go_live_date": c["go_live_date"],
                "forecast_annual_savings": (c["linked_opportunity"] or {}).get(
                    "estimated_annual_savings"
                ),
                "measured_annual_savings": (c["tracking"] or {}).get("measured_annual_savings"),
                "claimed_savings": (c["tracking"] or {}).get("total_realized_savings"),
                "payback_progress_pct": (c["tracking"] or {}).get("payback_progress_pct"),
            }
            for c in cases
        ],
        "timeline": timeline_data,
        "calibration": calibration.report(),
        "sources": [
            {
                "source_type": st,
                "rows_loaded": meta.get(st, {}).get("rows_loaded", 0),
                "origin": meta.get(st, {}).get("origin"),
                "updated_at": meta.get(st, {}).get("updated_at"),
            }
            for st in SOURCE_TYPES
        ],
    }


class SavingsRequest(BaseModel):
    entry_date: datetime.date
    amount: float
    note: Optional[str] = None


@app.post("/api/business-cases/{case_id}/savings")
def add_savings(case_id: str, body: SavingsRequest) -> Dict[str, Any]:
    case = db.add_savings_entry(
        case_id, body.entry_date.isoformat(), body.amount, body.note
    )
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    return case
