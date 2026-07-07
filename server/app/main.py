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

# --- authentication -------------------------------------------------------
# The hub is open until user profiles exist (demo mode). Once any user is
# registered, every /api call outside /api/auth requires a session token,
# and the session identity — not a self-reported name — drives role checks.
from contextvars import ContextVar

_CURRENT_USER: ContextVar[Optional[Dict[str, str]]] = ContextVar("current_user", default=None)


def _session_name() -> Optional[str]:
    user = _CURRENT_USER.get()
    return user["name"] if user else None


@app.middleware("http")
async def _auth_middleware(request, call_next):
    from fastapi.responses import JSONResponse
    path = request.url.path
    user = None
    token = (request.headers.get("authorization") or "")
    if token.lower().startswith("bearer "):
        user = db.session_user(token[7:])
    _CURRENT_USER.set(user)
    if (path.startswith("/api") and not path.startswith("/api/auth")
            and path != "/api/workspace/start"
            and user is None and db.list_users()):
        return JSONResponse({"detail": "Sign in required"}, status_code=401)
    return await call_next(request)


class StartRequest(BaseModel):
    name: str
    company: str
    email: str
    password: str


@app.post("/api/workspace/start")
def start_workspace(body: StartRequest) -> Dict[str, Any]:
    """The trial moment: wipe the sample data, name the workspace, and make
    the visitor its admin — one form between exploring and owning."""
    if not (body.name.strip() and body.company.strip() and body.password
            and "@" in body.email):
        raise HTTPException(400, "name, company, a valid email, and password are required")
    if db.list_users():
        raise HTTPException(403, "this workspace is already claimed — sign in instead")
    db.restore_state({"_format": 1, **{t: [] for t in (
        "ideas", "business_cases", "datasets", "strategic_initiatives",
        "challenges", "notifications", "events", "meta")}})
    db.meta_set("workspace_name", body.company.strip())
    db.meta_set("workspace_owner_email", body.email.strip())
    user = db.create_user(body.name.strip().lower(), "admin", body.password)
    db.audit("workspace.start", user["name"], detail=body.company.strip())
    return {"token": db.create_session(user["name"]), "user": user,
            "workspace": body.company.strip()}


class LoginRequest(BaseModel):
    name: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest) -> Dict[str, Any]:
    name = body.name.strip().lower()
    if not name or not body.password:
        raise HTTPException(400, "name and password are required")
    if not db.list_users():
        # first sign-in bootstraps the admin account
        user = db.create_user(name, "admin", body.password)
    else:
        user = db.verify_login(name, body.password)
        if user is None:
            raise HTTPException(401, "Wrong name or password — or no password set yet; "
                                     "ask an admin to set one in Hub Settings")
    db.audit("auth.login", user["name"])
    return {"token": db.create_session(user["name"]), "user": user}


class AccessRequest(BaseModel):
    name: str
    note: Optional[str] = None


@app.post("/api/auth/request-access")
def request_access(body: AccessRequest) -> Dict[str, Any]:
    if not body.name.strip():
        raise HTTPException(400, "your name is required")
    admins = [u["name"] for u in db.list_users() if u["role"] == "admin"]
    for a in admins:
        db.notify(a, "user", body.name.strip().lower(),
                  f"Access request: {body.name.strip()} wants to join this workspace"
                  + (f" — \"{body.note.strip()}\"" if body.note else "")
                  + ". Add them in Hub Settings → User profiles.")
    db.audit("auth.request_access", body.name.strip().lower())
    return {"ok": True, "admins_notified": len(admins)}


@app.get("/api/auth/me")
def me() -> Dict[str, Any]:
    return {"auth_required": bool(db.list_users()), "user": _CURRENT_USER.get(),
            "workspace": db.meta_get("workspace_name")}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if authorization and authorization.lower().startswith("bearer "):
        db.delete_session(authorization[7:])
    return {"ok": True}


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
    initiative_ids: Optional[List[str]] = None


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
    # tolerate stale tags (demo data can reset under an open browser): keep the
    # idea, drop tags that no longer resolve, and say so in the assessment
    tag_ids: List[str] = []
    dropped: List[str] = []
    seen: List[str] = []
    for iid in ([body.initiative_id] if body.initiative_id else []) + (body.initiative_ids or []):
        if iid and iid not in seen:
            seen.append(iid)
    initiatives = []
    for iid in seen:
        found = db.get_initiative(iid)
        if found is None:
            dropped.append(iid)
        else:
            tag_ids.append(iid)
            initiatives.append(found)
    initiative = initiatives[0] if initiatives else None
    opps = _prioritized_opps()
    assessment = hub.triage_idea(
        body.title, body.description, opps,
        category=body.category, estimated_annual_benefit=body.estimated_annual_benefit,
        benefit_type=body.benefit_type, horizon=body.horizon, challenge=challenge,
        initiative=initiative, existing_ideas=db.list_ideas(),
        beneficiary=body.beneficiary, pain_point=body.pain_point,
    )
    if dropped:
        assessment.setdefault("enrichment", []).append(
            "Dropped strategic-objective tag(s) that no longer exist "
            f"({', '.join(dropped)}) — likely stale after a demo data reset.")
    idea = db.create_idea(
        body.title.strip(), body.description.strip(),
        (body.submitter or "").strip() or _session_name(), assessment,
        category=(body.category or "").strip() or assessment.get("derived_category"),
        estimated_annual_benefit=body.estimated_annual_benefit,
        source=source, submitted_at=submitted_at,
        benefit_type=assessment.get("benefit_type"),
        horizon=assessment.get("horizon"),
        challenge_id=body.challenge_id,
        beneficiary=(body.beneficiary or "").strip() or None,
        pain_point=(body.pain_point or "").strip() or None,
        initiative_ids=tag_ids,
    )
    idea_tokens = hub._tokens(f"{idea['title']} {idea['description']}")
    for lesson in db.learnings(30):
        if lesson["outcome"] != "kill":
            continue
        if len(idea_tokens & hub._tokens(f"{lesson['hypothesis']} {lesson['learnings']}")) >= 3:
            db.cite_learning(idea["id"], lesson["case_id"])
            owner = db.submitter_for_case(lesson["case_id"])
            db.notify(owner, "case", lesson["case_id"],
                      f"Learning dividend: your experiment on '{lesson['case_title']}' just "
                      f"informed a new idea ('{idea['title']}'). Kills keep paying.")
    db.audit("idea.submit", idea.get("submitter"), idea["id"], idea["title"])
    db.log_automation(
        "idea_triage", assessment["recommendation"], idea["id"],
        assessment["rationale"][:200],
    )
    return idea


class AssistRequest(BaseModel):
    title: str
    description: Optional[str] = None


@app.post("/api/ideas/assist")
def assist_description(body: AssistRequest) -> Dict[str, Any]:
    if not body.title.strip():
        raise HTTPException(400, "a title is required before the hub can help with the description")
    return hub.assist_idea_description(body.title.strip(), (body.description or "").strip(),
                                       opportunities=_prioritized_opps())


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
    if idea["status"] != hub.workflow_keys()[-1]:
        raise HTTPException(
            400,
            "Business cases are developed at the final workflow gate only — advance the "
            "idea through the gates in the Command Center first.",
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


def _require_admin(authorization: Optional[str], actor: Optional[str] = None) -> None:
    """Configuration changes require the IVD_ADMIN_TOKEN bearer (when set) or,
    once user profiles exist, an actor with the admin role."""
    import os
    expected = os.environ.get("IVD_ADMIN_TOKEN")
    if expected:
        if authorization != f"Bearer {expected}":
            raise HTTPException(401, "Configuration changes require the admin token")
        return
    blocked = hub.check_role("admin", _session_name() or actor)
    if blocked:
        raise HTTPException(403, blocked)
    db.audit("settings.change", _session_name() or actor)


@app.put("/api/scoring-config")
def put_scoring_config(body: Dict[str, Any], authorization: Optional[str] = Header(None), actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    try:
        return hub.save_scoring_config(body)
    except hub.ConfigError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/users")
def get_users() -> Dict[str, Any]:
    return {"users": db.list_users(), "roles": hub.ROLES, "capabilities": hub.ROLE_CAPABILITIES}


@app.put("/api/users")
def put_users(body: Dict[str, Any], authorization: Optional[str] = Header(None),
              actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    users = body.get("users") or []
    seen = set()
    for u in users:
        if not (u.get("name") or "").strip():
            raise HTTPException(400, "every user needs a name")
        if u.get("role") not in hub.ROLES:
            raise HTTPException(400, f"role must be one of {hub.ROLES}")
        key = u["name"].strip().lower()
        if key in seen:
            raise HTTPException(400, f"duplicate user '{key}'")
        seen.add(key)
    return {"users": db.replace_users(users), "roles": hub.ROLES,
            "capabilities": hub.ROLE_CAPABILITIES}


@app.get("/api/governance")
def get_governance() -> Dict[str, Any]:
    return {"areas": hub.GOVERNANCE_AREAS, "assignments": hub.get_governance()}


@app.put("/api/governance")
def put_governance(body: Dict[str, List[str]], authorization: Optional[str] = Header(None), actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
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


def _workflow_position(status: str) -> int:
    keys = hub.workflow_keys()
    return keys.index(status) if status in keys else -1


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
    # run the same lazy automation the dashboard uses BEFORE assembling the
    # board, so the queue never lags one refresh behind a sweep — invisible
    # side effects were being misread as broken gate buttons
    automation = None
    if db.dataset_meta() and hub.automation_is_stale():
        automation = hub.run_automation(_prioritized_opps(), _loaded_datasets(),
                                        db.dataset_meta())
    ideas = db.list_ideas()
    cases = db.list_business_cases()

    def _with_checklist(items):
        return [{**i, "gate_checklist": hub.gate_checklist(i),
                 "review_summary": db.review_summary(i["id"])} for i in items]

    steps = hub.get_workflow()
    return {
        "idea_steps": [
            {**s, "position": i, "is_last": i == len(steps) - 1,
             "ideas": _with_checklist([x for x in ideas if x["status"] == s["key"]])}
            for i, s in enumerate(steps)
        ],
        "idea_backlog": [
            {**i, "held_reason": next((e["comment"] for e in reversed(db.events_for("idea", i["id"]))
                                       if e["action"] == "hold"), None)}
            for i in ideas if i["status"] == "backlog"],
        "cases_pending_approval": [c for c in cases if c["stage"] in ("draft", "proposed")],
        "cases_in_experiment": [c for c in cases if c["stage"] == "experiment"],
        "cases_in_motion": [
            {**c, "approved_by": next((e["actor"] for e in reversed(db.events_for("case", c["id"]))
                                       if e["action"] == "approve"), None),
             "approved_at": next((e["created_at"][:10] for e in reversed(db.events_for("case", c["id"]))
                                  if e["action"] == "approve"), None)}
            for c in cases if c["stage"] in ("approved", "in_delivery")],
        "history": db.workflow_events(30),
        "governance": hub.get_governance(),
        "automation_ran": automation,
        "cost_of_delay": _cost_of_delay(
            [i for i in ideas if i["status"] not in ("business_case", "declined", "backlog")]),
    }


@app.post("/api/command/decide")
def command_decide(body: DecisionRequest) -> Dict[str, Any]:
    if body.subject_type not in ("idea", "case"):
        raise HTTPException(400, "subject_type must be 'idea' or 'case'")
    valid = ("approve", "advance", "reject", "feedback", "experiment",
             "qualify", "prioritize", "hold", "develop", "resume")
    if body.decision not in valid:
        raise HTTPException(400, f"decision must be one of {valid}")
    db.audit(f"decide.{body.decision}", _session_name() or body.actor,
             body.subject_id, body.comment)

    if body.subject_type == "idea":
        idea = db.get_idea(body.subject_id)
        if idea is None:
            raise HTTPException(404, f"Idea '{body.subject_id}' not found")
        decision = body.decision
        if decision == "experiment":
            raise HTTPException(400, "experiment applies to cases, not ideas")
        steps = hub.get_workflow()
        keys = [s["key"] for s in steps]
        pos = _workflow_position(idea["status"])
        # legacy + alias decisions map onto the configured sequence
        if decision == "approve":
            decision = "develop" if pos == len(keys) - 1 else "advance" if pos >= 0 else None
            if decision is None:
                raise HTTPException(400, f"No forward gate from status '{idea['status']}'")
        if decision == "qualify":
            if pos != 0:
                raise HTTPException(400, f"'qualify' applies at the first gate (status: {idea['status']})")
            decision = "advance"
        if decision == "prioritize":
            if pos != len(keys) - 2:
                raise HTTPException(400, f"'prioritize' applies at the gate before development (status: {idea['status']})")
            decision = "advance"

        if decision == "resume":
            if idea["status"] != "backlog":
                raise HTTPException(400, "only backlog ideas can be resumed")
            blocked = hub.check_role("reviewer", _session_name() or body.actor)
            if blocked:
                raise HTTPException(403, blocked)
            target = keys[1] if len(keys) > 1 else keys[0]
            db.update_idea(idea["id"], target)
            db.add_workflow_event("idea", idea["id"], "resume", body.actor, body.comment)
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"Your idea '{idea['title']}' is back in review.")
            return {"result": {"idea": db.get_idea(idea["id"])}}
        if pos < 0 and decision in ("advance", "develop", "hold"):
            raise HTTPException(400, f"No forward gate from status '{idea['status']}'")
        minimum = "contributor" if decision == "feedback" else "reviewer"
        blocked = hub.check_role(minimum, _session_name() or body.actor)
        if blocked:
            raise HTTPException(403, blocked)
        area = steps[pos]["forum"] if pos >= 0 else "idea_screening"
        blocked = hub.check_authority(area, body.actor)
        if blocked:
            raise HTTPException(403, blocked)
        db.add_workflow_event("idea", body.subject_id, decision, body.actor, body.comment)

        if decision == "advance":
            if pos >= len(keys) - 1:
                raise HTTPException(400, "This idea is at the development gate — use 'develop'")
            next_step = steps[pos + 1]
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"Your idea '{idea['title']}' passed the {steps[pos]['gate']} gate and moved to {next_step['label']}.")
            return {"result": db.update_idea(body.subject_id, next_step["key"])}
        if decision == "hold":
            if pos == 0:
                raise HTTPException(400, "Ideas at intake are qualified or declined, not held")
            db.notify(idea.get("submitter"), "idea", idea["id"],
                      f"'{idea['title']}' is on the backlog — awaiting portfolio capacity.")
            return {"result": db.update_idea(body.subject_id, "backlog")}
        if decision == "develop":
            if pos != len(keys) - 1:
                raise HTTPException(400, "Business cases are developed at the final workflow gate only")
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
    blocked = hub.check_role("contributor" if body.decision == "feedback" else "executive",
                             _session_name() or body.actor)
    if blocked:
        raise HTTPException(403, blocked)
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
        tagged_ideas = [i for i in ideas
                        if initiative["id"] in (i.get("initiative_ids") or [])]
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
    return {"demo": demo.status(), "industries": demo.INDUSTRIES,
            "seeded": bool(db.meta_get("seeded_lifecycle"))}


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
    blocked = hub.check_role("executive", _session_name() or body.actor) or hub.check_authority(
        "business_case_approval", body.actor)
    if blocked:
        raise HTTPException(403, blocked)
    db.audit("funding.release", _session_name() or body.actor, case_id)
    case = db.release_tranche(case_id, tranche_id, body.actor)
    if case is None:
        raise HTTPException(404, f"Planned tranche {tranche_id} not found on '{case_id}'")
    db.add_workflow_event("case", case_id, "tranche_released", body.actor,
                          f"tranche {tranche_id}")
    return case


# --------------------------------------------------------------- notifications

class ReviseRequest(BaseModel):
    description: str
    title: Optional[str] = None
    estimated_annual_benefit: Optional[float] = None
    actor: Optional[str] = None


@app.put("/api/ideas/{idea_id}/revise")
def revise_idea(idea_id: str, body: ReviseRequest) -> Dict[str, Any]:
    """Close the feedback loop: the submitter answers reviewer feedback by
    revising the idea in place — it re-triages and returns to the queue."""
    idea = db.get_idea(idea_id)
    if idea is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    if idea["status"] in ("declined", "business_case"):
        raise HTTPException(400, f"ideas in status '{idea['status']}' can't be revised")
    if not body.description.strip():
        raise HTTPException(400, "a description is required")
    db.update_idea_fields(idea_id, (body.title or idea["title"]).strip(),
                          body.description.strip(), body.estimated_annual_benefit)
    fresh = _rescore_idea(idea_id)
    actor = _session_name() or body.actor or idea.get("submitter")
    db.add_workflow_event("idea", idea_id, "revise", actor, "revised after feedback")
    db.audit("idea.revise", actor, idea_id)
    return fresh


@app.get("/api/my-submissions")
def my_submissions(submitter: str = Query(...)) -> Dict[str, Any]:
    """A submitter's ideas with their full approval chain: gate history,
    case stage history when promoted, and whether the ball is in their court.
    Admins see every submission across the hub, not just their own."""
    user = _CURRENT_USER.get()
    is_admin = bool(user and user.get("role") == "admin")
    if is_admin:
        mine = db.list_ideas()
    else:
        mine = [i for i in db.list_ideas()
                if (i.get("submitter") or "").strip().lower() == submitter.strip().lower()]
    out = []
    for idea in mine:
        history = db.events_for("idea", idea["id"])
        case = db.get_business_case(idea["promoted_case_id"]) if idea.get("promoted_case_id") else None
        needs_info = (idea.get("assessment") or {}).get("recommendation") == "needs_info"
        awaiting_fix = bool(history) and history[-1]["action"] == "feedback"
        reason = None
        if needs_info:
            reason = "Intake guardrails not met — add the missing information and resubmit details to a reviewer."
        elif awaiting_fix:
            reason = f"A reviewer left feedback: {history[-1]['comment'] or '(see history)'}"
        out.append({
            **idea,
            "history": history,
            "case_stage": case["stage"] if case else None,
            "case_stage_history": case["stage_history"] if case else [],
            "case_history": db.events_for("case", idea["promoted_case_id"]) if case else [],
            "needs_attention": bool(reason),
            "attention_reason": reason,
        })
    return {
        "scope": "all" if is_admin else "mine",
        "ideas": out,
        "updates_needed": [x["id"] for x in out if x["needs_attention"]],
        "workflow": hub.get_workflow(),
    }


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


@app.get("/api/workflow")
def get_workflow() -> Dict[str, Any]:
    return {"steps": hub.get_workflow(), "forums": hub.GOVERNANCE_AREAS}


@app.put("/api/workflow")
def put_workflow(body: Dict[str, Any], authorization: Optional[str] = Header(None), actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    try:
        return {"steps": hub.save_workflow(body.get("steps") or [])}
    except hub.ConfigError as exc:
        raise HTTPException(400, str(exc))


class InitiativeUpdate(BaseModel):
    name: Optional[str] = None
    objective: Optional[str] = None


@app.put("/api/initiatives/{initiative_id}")
def update_initiative(initiative_id: str, body: InitiativeUpdate) -> Dict[str, Any]:
    updated = db.update_initiative(initiative_id, body.name, body.objective)
    if updated is None:
        raise HTTPException(404, f"Initiative '{initiative_id}' not found")
    return updated


class ReorderRequest(BaseModel):
    ids: List[str]


@app.post("/api/initiatives/reorder")
def reorder_initiatives(body: ReorderRequest) -> Dict[str, Any]:
    db.reorder_initiatives(body.ids)
    return list_initiatives()


class ChallengeUpdate(BaseModel):
    title: Optional[str] = None
    question: Optional[str] = None
    theme: Optional[str] = None


@app.put("/api/challenges/{challenge_id}")
def update_challenge(challenge_id: str, body: ChallengeUpdate) -> Dict[str, Any]:
    updated = db.update_challenge(challenge_id, body.title, body.question, body.theme)
    if updated is None:
        raise HTTPException(404, f"Challenge '{challenge_id}' not found")
    return updated


@app.get("/api/pipeline")
def pipeline() -> Dict[str, Any]:
    return hub.build_pipeline(db.list_ideas(), db.list_business_cases())


@app.get("/api/lifecycle")
def lifecycle() -> Dict[str, Any]:
    """The stage-gate model with live counts, plus the portfolio register
    (impact vs readiness) for qualified/prioritized ideas."""
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    idea_counts = {stage: 0 for stage in hub.IDEA_STAGES_DYNAMIC()}
    for i in ideas:
        if i["status"] in idea_counts:
            idea_counts[i["status"]] += 1
    case_counts = {stage: 0 for stage in db.STAGES}
    for c in cases:
        case_counts[c["stage"]] = case_counts.get(c["stage"], 0) + 1

    middle_keys = set(hub.workflow_keys()[1:])
    register = []
    for i in ideas:
        if i["status"] not in middle_keys:
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
        "spec": hub.lifecycle_spec(),
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

# ---------------------------------------------- enterprise admin: audit + state

@app.get("/api/admin/audit")
def audit_trail(authorization: Optional[str] = Header(None),
                actor: Optional[str] = Query(None),
                format: str = Query("json")) -> Any:
    _require_admin(authorization, actor)
    entries = db.audit_entries()
    if format == "csv":
        from fastapi.responses import PlainTextResponse
        lines = ["at,actor,action,subject,detail"]
        for e in entries:
            row = [str(e.get(k) or "").replace('"', "'") for k in
                   ("at", "actor", "action", "subject", "detail")]
            lines.append(",".join(f'"{v}"' for v in row))
        return PlainTextResponse("\n".join(lines), media_type="text/csv",
                                 headers={"Content-Disposition":
                                          "attachment; filename=audit-trail.csv"})
    return {"entries": entries}


@app.get("/api/admin/export")
def export_state(authorization: Optional[str] = Header(None),
                 actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    db.audit("state.export", _session_name() or actor)
    return db.dump_state()


@app.post("/api/admin/import")
def import_state(body: Dict[str, Any], authorization: Optional[str] = Header(None),
                 actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    try:
        counts = db.restore_state(body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.audit("state.import", _session_name() or actor,
             detail=f"{sum(counts.values())} rows across {len(counts)} tables")
    return {"restored": counts}


# ------------------------------------------- capture webhook + delivery handoff

@app.post("/api/integrations/capture")
def capture_idea(body: Dict[str, Any]) -> Dict[str, Any]:
    """Generic inbound capture for Teams/Slack/email middleware: any system
    that can POST JSON can feed the funnel."""
    import os
    expected = os.environ.get("IVD_CAPTURE_TOKEN")
    if expected and body.get("token") != expected:
        raise HTTPException(401, "invalid capture token")
    title = (body.get("title") or body.get("text") or "").strip()
    if not title:
        raise HTTPException(400, "a 'title' (or 'text') field is required")
    idea = _ingest_idea(IdeaRequest(
        title=title[:140],
        description=(body.get("description") or body.get("text") or title).strip(),
        submitter=(body.get("submitter") or body.get("user") or "").strip() or None,
    ), source=f"capture:{(body.get('source') or 'webhook')[:30]}")
    db.audit("idea.capture", idea.get("submitter"), idea["id"],
             f"via {body.get('source') or 'webhook'}")
    return {"id": idea["id"], "status": idea["status"],
            "recommendation": (idea.get("assessment") or {}).get("recommendation")}


@app.get("/api/business-cases/{case_id}/handoff")
def delivery_handoff(case_id: str) -> Dict[str, Any]:
    """Delivery handoff package: everything Jira/Azure DevOps needs to open
    an epic, including the measurement plan the delivery team must honor."""
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    plan = case["roi_plan"]
    funding = case.get("funding") or {}
    return {
        "issue_type": "Epic",
        "summary": case["title"],
        "description": (
            f"{plan.get('summary', case['description'])}\n\n"
            "== Measurement plan (do not ship without) ==\n"
            + "\n".join(f"- KPI: {k['name']} | target {k['target']} | "
                         f"sources: {', '.join(k['data_sources'])}"
                         for k in plan.get("kpis", []))
            + f"\n\nROI formula: {plan.get('roi_formula', 'n/a')}"
        ),
        "labels": ["innovation-hub", case["id"], case.get("stage") or ""],
        "budget_released": funding.get("released", 0),
        "budget_planned": funding.get("planned", 0),
        "go_live_target": case.get("go_live_date"),
        "hub_case_id": case["id"],
    }


# -------------------------------------------------- board pack + value ledger

@app.get("/api/reports/board-pack")
def board_pack(format: str = Query("md")) -> Any:
    """One-page markdown board pack: the numbers leadership asks for, in the
    order they ask for them — claimed and verified value never blended."""
    from fastapi.responses import PlainTextResponse
    d = dashboard()
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    verified = sum(
        (b.get("annualized_delta") or 0)
        for c in cases for b in c.get("metric_bindings", []))
    claimed = sum(e["amount"] for c in cases for e in c.get("savings_entries", []))
    released = sum((c.get("funding") or {}).get("released", 0) for c in cases)
    prior = db.snapshot_before(datetime.date.today().isoformat())
    lines = [
        f"# {db.meta_get('workspace_name') or 'Innovation Hub'} — Board Pack",
        f"_Generated {datetime.date.today().isoformat()}_",
        "",
        f"**Headline:** {d.get('headline', {}).get('text', 'n/a') if isinstance(d.get('headline'), dict) else d.get('headline', 'n/a')}",
        "",
        "## Value (verified vs claimed — never blended)",
        f"- Verified annual value (computed from data): ${verified:,.0f}"
        + (f" ({'+' if verified - prior['verified'] >= 0 else ''}"
           f"${verified - prior['verified']:,.0f} vs {prior['day']})" if prior else ""),
        f"- Claimed savings to date (self-reported): ${claimed:,.0f}",
        f"- Funding released through gated tranches: ${released:,.0f}",
        "",
        "## Pipeline",
        f"- Ideas in flight: {len([i for i in ideas if i['status'] not in ('declined',)])}"
        f" ({len([i for i in ideas if i['status'] == 'business_case'])} promoted to business case)",
        f"- Business cases: {len(cases)} — "
        + ", ".join(f"{stage}: {n}" for stage, n in sorted(
            __import__('collections').Counter(c['stage'] for c in cases).items())),
        "",
        "## Decisions waiting",
    ]
    q_ideas = [i for i in ideas if i["status"] not in ("business_case", "declined", "backlog")]
    for i in q_ideas[:5]:
        a = i.get("assessment") or {}
        lines.append(f"- {i['title']} (score {a.get('score', '—')}, {i['status']})")
    lines += ["", "## Kills & learnings",
              f"- Experiments concluded with learnings captured: "
              f"{sum(1 for c in cases for e in c.get('experiments', []) if e.get('outcome'))}"]
    if format == "html":
        from fastapi.responses import HTMLResponse
        import html as _h
        body = ""
        for ln in lines:
            t = _h.escape(ln)
            if ln.startswith("# "):
                body += f"<h1>{t[2:]}</h1>"
            elif ln.startswith("## "):
                body += f"<h2>{t[3:]}</h2>"
            elif ln.startswith("- "):
                body += f"<li>{t[2:]}</li>"
            elif ln.startswith("**"):
                body += f"<p><strong>{t.replace('**', '')}</strong></p>"
            elif ln.startswith("_"):
                body += f"<p><em>{t.strip('_')}</em></p>"
            elif ln:
                body += f"<p>{t}</p>"
        return HTMLResponse(
            "<html><head><title>Innovation Hub — Board Pack</title><style>"
            "body{font-family:-apple-system,system-ui,sans-serif;max-width:720px;"
            "margin:2rem auto;color:#111;line-height:1.5}h1{border-bottom:2px solid #4cc38a;"
            "padding-bottom:.3rem}h2{color:#2d7a57;margin-top:1.4rem}li{margin:.2rem 0}"
            "@media print{body{margin:0}}</style></head><body>"
            + body + "<script>window.print()</script></body></html>")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown",
                             headers={"Content-Disposition":
                                      "attachment; filename=board-pack.md"})


@app.get("/api/deltas")
def metric_deltas() -> Dict[str, Any]:
    """Leaders manage deltas, not snapshots: today's core numbers vs the
    prior recorded day, plus data freshness."""
    cases = db.list_business_cases()
    verified = round(sum((b.get("annualized_delta") or 0)
                         for c in cases for b in c.get("metric_bindings", [])), 2)
    claimed = round(sum(e["amount"] for c in cases for e in c.get("savings_entries", [])), 2)
    ideas_n = len(db.list_ideas())
    today = datetime.date.today().isoformat()
    db.record_snapshot(today, verified, claimed, ideas_n, len(cases))
    prior = db.snapshot_before(today)
    if prior and prior["day"] == today:
        prior = None
    observed = [o["observed_at"] for c in cases for b in c.get("metric_bindings", [])
                for o in b.get("observations", [])]
    return {
        "as_of": today,
        "verified": verified,
        "verified_delta": round(verified - prior["verified"], 2) if prior else None,
        "claimed_delta": round(claimed - prior["claimed"], 2) if prior else None,
        "ideas_delta": ideas_n - prior["ideas"] if prior else None,
        "since": prior["day"] if prior else None,
        "last_observed_at": max(observed) if observed else None,
    }


@app.get("/api/business-cases/{case_id}/financials")
def case_financials(case_id: str, horizon_years: int = Query(3, ge=1, le=7),
                    discount_rate: float = Query(0.10, ge=0.0, le=0.5),
                    benefit_override: Optional[float] = Query(None, ge=0),
                    cost_override: Optional[float] = Query(None, ge=0),
                    ramp: float = Query(0.6, ge=0.0, le=1.0),
                    run_rate_pct: float = Query(0.15, ge=0.0, le=1.0)) -> Dict[str, Any]:
    """CFO-grade financial model for one case, grounded in customer data:
    benefits come from the matched opportunity detected in their own systems
    (calibration-discounted), verified actuals override forecasts once
    observed, and every assumption is listed with its source."""
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    factors = calibration.factors()
    grounding, assumptions = [], []

    opp = case.get("linked_opportunity")
    verified = sum((b.get("annualized_delta") or 0) for b in case.get("metric_bindings", []))
    if verified > 0:
        annual_benefit = verified
        grounding.append("Annual benefit uses VERIFIED value re-observed from source data "
                         "(frozen-baseline metric bindings) — not a forecast.")
    elif opp:
        f = factors.get(opp.get("category", ""), 0.7)
        annual_benefit = (opp.get("estimated_annual_savings") or 0) * f
        grounding.append(f"Annual benefit derived from opportunity {opp.get('id')} detected "
                         f"in the customer's own data, discounted by the learned realization "
                         f"factor {f:.2f} for '{opp.get('category')}'.")
    else:
        annual_benefit = case.get("estimated_annual_benefit") or 0
        assumptions.append("Benefit is submitter-estimated — no matched customer data; "
                           "treat as low confidence until bindings observe actuals.")

    if benefit_override is not None:
        annual_benefit = benefit_override
        grounding, assumptions = [], ["Annual benefit set by the approver as a modeling input."]
    funding = case.get("funding") or {}
    implementation_cost = (cost_override if cost_override is not None else
                           funding.get("planned") or case.get("estimated_cost")
                           or annual_benefit * 0.3)
    if cost_override is not None:
        assumptions.append("Implementation cost set by the approver as a modeling input.")
    if funding.get("planned"):
        grounding.append("Implementation cost equals planned funding tranches — the amounts "
                         "governance actually committed.")
    else:
        assumptions.append("Implementation cost estimated (no tranches planned yet); "
                           "default heuristic 30% of first-year benefit when unstated.")
    run_rate = implementation_cost * run_rate_pct
    assumptions.append(f"Ongoing run cost at {run_rate_pct:.0%} of implementation cost per year.")
    assumptions.append(f"Year-1 benefit ramps at {ramp:.0%} (partial-year adoption); full run-rate after.")

    cash_flows, cumulative, payback_months = [], -implementation_cost, None
    for year in range(1, horizon_years + 1):
        benefit = annual_benefit * (ramp if year == 1 else 1.0)
        net = benefit - run_rate
        cash_flows.append({"year": year, "benefit": round(benefit, 2),
                           "cost": round(run_rate, 2), "net": round(net, 2)})
        if payback_months is None and net > 0:
            prev = cumulative
            cumulative += net
            if cumulative >= 0:
                payback_months = round((year - 1 + (-prev / net)) * 12, 1)
        else:
            cumulative += net
    tcv = sum(cf["benefit"] for cf in cash_flows)
    total_cost = implementation_cost + run_rate * horizon_years
    npv = -implementation_cost + sum(
        cf["net"] / ((1 + discount_rate) ** cf["year"]) for cf in cash_flows)
    roi_pct = ((tcv - total_cost) / total_cost * 100) if total_cost > 0 else None
    return {
        "case_id": case_id,
        "horizon_years": horizon_years,
        "discount_rate": discount_rate,
        "annual_benefit": round(annual_benefit, 2),
        "implementation_cost": round(implementation_cost, 2),
        "tcv": round(tcv, 2),
        "total_cost": round(total_cost, 2),
        "npv": round(npv, 2),
        "roi_pct": round(roi_pct, 1) if roi_pct is not None else None,
        "payback_months": payback_months,
        "cash_flows": [{**cf} for cf in cash_flows],
        "data_grounding": grounding,
        "assumptions": assumptions,
        "benefit_basis": ("verified" if verified > 0 else
                          "detected_opportunity" if opp else "submitter_estimate"),
    }


# Industry reference ranges for innovation portfolio management. External,
# directional figures for orientation — clearly labeled, never blended with
# the customer's own computed metrics.
_PEER_REFERENCES = [
    ("Claimed value that gets verified", "verification_ratio", 0.25, 0.45,
     "Most programs verify 25-45% of claimed value; best-in-class exceed 60%"),
    ("Ideas reaching business case", "idea_to_case_ratio", 0.10, 0.25,
     "Healthy funnels convert 10-25% of ideas; higher often means weak intake filters"),
    ("Experiment kill rate", "kill_rate", 0.20, 0.40,
     "Leaders kill 20-40% of experiments; near-zero kill rates signal theater"),
    ("Transformational (H3) share of pipeline value", "h3_share", 0.05, 0.15,
     "The 70/20/10 rule implies ~10% in transformational bets"),
]


@app.get("/api/portfolio/advisory")
def portfolio_advisory() -> Dict[str, Any]:
    """The portfolio-management view: balance vs the 70/20/10 target,
    concentration risk, peer reference comparison, and recommended actions —
    computed from this hub's own live pipeline."""
    ideas = db.list_ideas()
    cases = db.list_business_cases()
    active = [c for c in cases if c["stage"] not in ("closed",)]

    def case_value(c):
        return (c.get("estimated_annual_benefit")
                or (c.get("linked_opportunity") or {}).get("estimated_annual_savings") or 0)

    total_value = sum(case_value(c) for c in active) or 1.0
    horizon_share = {"h1": 0.0, "h2": 0.0, "h3": 0.0}
    for c in active:
        horizon_share[c.get("horizon") or "h1"] = \
            horizon_share.get(c.get("horizon") or "h1", 0) + case_value(c) / total_value
    balance = [{"horizon": h, "share": round(v, 3), "target": t,
                "verdict": "over" if v > t + 0.12 else "under" if v < t - 0.12 else "on-target"}
               for (h, v), t in zip(sorted(horizon_share.items()), (0.70, 0.20, 0.10))]

    top = max((case_value(c) for c in active), default=0)
    concentration = round(top / total_value, 3)

    claimed = sum(e["amount"] for c in cases for e in c.get("savings_entries", []))
    verified = sum((b.get("annualized_delta") or 0)
                   for c in cases for b in c.get("metric_bindings", []))
    experiments = [e for c in cases for e in c.get("experiments", []) if e.get("outcome")]
    ours = {
        "verification_ratio": round(verified / claimed, 3) if claimed else None,
        "idea_to_case_ratio": round(len(cases) / len(ideas), 3) if ideas else None,
        "kill_rate": round(sum(1 for e in experiments if e["outcome"] == "kill")
                           / len(experiments), 3) if experiments else None,
        "h3_share": round(horizon_share.get("h3", 0), 3),
    }
    peers = [{"metric": label, "key": key, "ours": ours[key], "peer_low": lo,
              "peer_high": hi, "note": note,
              "verdict": (None if ours[key] is None else
                          "above" if ours[key] > hi else "below" if ours[key] < lo else "in-range")}
             for label, key, lo, hi, note in _PEER_REFERENCES]

    recs = []
    if horizon_share.get("h3", 0) < 0.05:
        recs.append({"key": "fund_h3", "title": "Fund transformational bets",
                     "why": f"Only {horizon_share.get('h3', 0):.0%} of pipeline value is H3 "
                            "against a ~10% target — the portfolio skews incremental.",
                     "action": "Launch a challenge scoped to horizon-3 plays and ring-fence a tranche."})
    if concentration > 0.4:
        recs.append({"key": "concentration", "title": "Reduce single-bet concentration",
                     "why": f"{concentration:.0%} of active pipeline value sits in one case.",
                     "action": "Stage its funding in smaller tranches and accelerate two mid-size cases."})
    if ours["verification_ratio"] is not None and ours["verification_ratio"] < 0.25:
        recs.append({"key": "verification", "title": "Tighten measurement discipline",
                     "why": f"Only {ours['verification_ratio']:.0%} of claimed value is verified — "
                            "below the 25-45% peer range.",
                     "action": "Require metric bindings before approval; re-observe live cases monthly."})
    if ours["kill_rate"] is not None and ours["kill_rate"] < 0.2:
        recs.append({"key": "kill_rate", "title": "Kill more, earlier",
                     "why": f"Kill rate {ours['kill_rate']:.0%} is below the 20-40% peer range — "
                            "weak experiments are surviving.",
                     "action": "Demand explicit success criteria and a kill review at every tranche gate."})
    backlogged = [i for i in ideas if i["status"] == "backlog"]
    if len(backlogged) >= 3:
        recs.append({"key": "backlog", "title": "Clear the backlog",
                     "why": f"{len(backlogged)} qualified ideas are parked with no review date.",
                     "action": "Resume or decline each — parked value is unmanaged value."})
    if not recs:
        recs.append({"key": None, "title": "Hold course",
                     "why": "Balance, concentration, and measurement are all within healthy ranges.",
                     "action": "Revisit after the next funding cycle."})

    return {"purpose": "Advisory window: is this portfolio balanced, honest, and "
                       "positioned against peers — and what should leadership do next?",
            "total_pipeline_value": round(total_value, 2),
            "balance": balance, "concentration_top_case": concentration,
            "ours": ours, "peer_comparison": peers,
            "peer_note": "Peer figures are external industry reference ranges "
                         "(directional); your metrics are computed from this hub's data.",
            "recommendations": recs}


class ExecuteRecRequest(BaseModel):
    key: str
    actor: Optional[str] = None


@app.post("/api/portfolio/advisory/execute")
def execute_recommendation(body: ExecuteRecRequest) -> Dict[str, Any]:
    """Execute an advisory recommendation inside the app — AI does the
    drafting, the platform does the plumbing, and everything lands as real,
    auditable objects (challenges, tranches, observations, queue moves)."""
    actor = _session_name() or body.actor or "portfolio-advisory"
    if body.key == "fund_h3":
        draft = hub.radar_scan("transformational horizon-three innovation bets beyond our core business")
        challenge = create_challenge(ChallengeRequest(
            title=f"H3 campaign: {draft['challenge_title']}",
            question=draft["challenge_question"], theme="h3-transformational"))
        db.audit("advisory.execute", actor, challenge["id"], "fund_h3 campaign launched")
        return {"done": f"Launched the H3 campaign '{challenge['title']}' — "
                        f"{len(draft['starter_ideas'])} AI starter ideas suggested.",
                "details": draft["starter_ideas"], "challenge_id": challenge["id"]}
    if body.key == "concentration":
        cases = [c for c in db.list_business_cases() if c["stage"] not in ("closed",)]
        if not cases:
            raise HTTPException(400, "no active cases")
        biggest = max(cases, key=lambda c: (c.get("estimated_annual_benefit")
                      or (c.get("linked_opportunity") or {}).get("estimated_annual_savings") or 0))
        val = (biggest.get("estimated_annual_benefit")
               or (biggest.get("linked_opportunity") or {}).get("estimated_annual_savings") or 0)
        add_tranche(biggest["id"], TrancheRequest(
            label="De-risking checkpoint", amount=max(round(val * 0.1, 2), 1000),
            milestone="Concentration review: evidence before further commitment"))
        db.audit("advisory.execute", actor, biggest["id"], "concentration checkpoint tranche")
        return {"done": f"Added a milestone-gated de-risking tranche to '{biggest['title']}' — "
                        "further capital now requires an evidence checkpoint.", "details": []}
    if body.key == "verification":
        observed = 0
        for c in db.list_business_cases():
            for b in c.get("metric_bindings", []):
                try:
                    observe_binding(c["id"], b["id"])
                    observed += 1
                except Exception:
                    pass
        db.audit("advisory.execute", actor, None, f"re-measured {observed} bindings")
        return {"done": f"Re-measured {observed} frozen-baseline metric(s) across the portfolio "
                        "from current source data.", "details": []}
    if body.key == "kill_rate":
        notified = 0
        for c in db.list_business_cases():
            if c["stage"] == "experiment":
                db.notify(db.submitter_for_case(c["id"]), "case", c["id"],
                          f"Kill review scheduled for the experiment on '{c['title']}': bring "
                          "evidence against the success criteria — surviving without evidence "
                          "is not an option.")
                notified += 1
        db.audit("advisory.execute", actor, None, f"kill reviews on {notified} experiments")
        return {"done": f"Scheduled kill reviews on {notified} open experiment(s) — owners "
                        "notified to bring evidence against their success criteria.", "details": []}
    if body.key == "backlog":
        resumed = []
        for i in db.list_ideas():
            if i["status"] == "backlog":
                command_decide(DecisionRequest(subject_type="idea", subject_id=i["id"],
                                               decision="resume", actor=actor,
                                               comment="resumed by portfolio advisory"))
                resumed.append(i["title"])
        db.audit("advisory.execute", actor, None, f"resumed {len(resumed)} backlog ideas")
        return {"done": f"Resumed {len(resumed)} parked idea(s) back into review — "
                        "no more unmanaged value.", "details": resumed}
    raise HTTPException(400, f"unknown recommendation key '{body.key}'")


class StudioRequest(BaseModel):
    kind: str
    topic: str
    horizon: str = "3-7y"


@app.post("/api/ideate/studio")
def ideate_studio(body: StudioRequest) -> Dict[str, Any]:
    if body.kind not in ("futures", "competitive", "maturity", "ten_types"):
        raise HTTPException(400, "kind must be futures|competitive|maturity|ten_types")
    if not body.topic.strip():
        raise HTTPException(400, "a topic is required")
    out = hub.ideate_studio(body.kind, body.topic.strip(), body.horizon)
    db.save_studio_run(body.kind, body.topic.strip(), body.horizon, out)
    db.audit(f"ideate.{body.kind}", _session_name(), None, body.topic[:80])
    return out


@app.post("/api/demo/clear")
def demo_clear(authorization: Optional[str] = Header(None),
               actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Clear all demo/business data. The only sanctioned way to empty the hub;
    until pressed, cold starts re-seed the demo so it never vanishes mid-use."""
    _require_admin(authorization, actor)
    db.restore_state({"_format": 1, **{t: [] for t in (
        "ideas", "business_cases", "datasets", "strategic_initiatives",
        "challenges", "notifications", "workflow_events", "studio_runs",
        "learning_citations", "metric_snapshots")}})
    db.meta_set("seeded_lifecycle", "")
    db.meta_set("demo_cleared", "1")
    db.audit("demo.clear", _session_name() or actor)
    return {"cleared": True}


_TYPE_KEYWORDS = {
    "Profit Model": ["pricing", "subscription", "revenue model", "monetiz", "license", "contract"],
    "Network": ["partner", "ecosystem", "alliance", "vendor", "supplier network"],
    "Structure": ["org", "team structure", "talent", "reorganiz", "roles"],
    "Process": ["automat", "process", "workflow", "rpa", "provisioning", "matching", "routing"],
    "Product Performance": ["feature", "faster", "quality", "performance", "upgrade"],
    "Product System": ["platform", "integration", "suite", "bundle", "api"],
    "Service": ["support", "service desk", "onboarding", "self-service", "helpdesk", "resets"],
    "Channel": ["portal", "mobile app", "channel", "storefront", "distribution"],
    "Brand": ["brand", "reputation", "trust mark", "positioning"],
    "Customer Engagement": ["customer experience", "engagement", "personaliz", "tracker", "notification"],
}


class CompetitiveIntake(BaseModel):
    product: str
    description: Optional[str] = None
    segment: Optional[str] = None
    competitors: Optional[List[str]] = None
    audience: Optional[str] = None
    decision: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/ideate/competitive-report")
def competitive_report(body: CompetitiveIntake) -> Dict[str, Any]:
    if not body.product.strip():
        raise HTTPException(400, "product name is required")
    report = hub.competitive_report(body.model_dump())
    db.save_studio_run("competitive_report", body.product.strip(), None, report)
    db.audit("ideate.competitive_report", _session_name(), None, body.product[:80])
    return report


@app.get("/api/ideate/competitive-reports")
def list_competitive_reports() -> Dict[str, Any]:
    with db._conn() as conn:
        rows = conn.execute("SELECT id, topic, created_at FROM studio_runs "
                            "WHERE kind='competitive_report' ORDER BY id DESC LIMIT 20").fetchall()
    return {"reports": [dict(r) for r in rows]}


@app.get("/api/ideate/competitive-reports/{run_id}")
def get_competitive_report(run_id: int) -> Dict[str, Any]:
    import json as _json
    with db._conn() as conn:
        row = conn.execute("SELECT topic, output, created_at FROM studio_runs "
                           "WHERE id=? AND kind='competitive_report'", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "report not found")
    return {"topic": row["topic"], "created_at": row["created_at"],
            **_json.loads(row["output"])}


@app.post("/api/ideate/tentypes-concepts")
def tentypes_concepts(body: StudioRequest) -> Dict[str, Any]:
    out = hub.tentypes_concepts(body.topic.strip() or "our business")
    db.save_studio_run("tentypes_concepts", body.topic.strip(), None, out)
    return out


@app.get("/api/ideate/tentypes-mirror")
def tentypes_mirror() -> Dict[str, Any]:
    """The mirror: your own pipeline classified across Keeley's ten types —
    empty cells are the strategic headline."""
    items = [(i["id"], f"{i['title']} {i['description']}", i["title"])
             for i in db.list_ideas() if i["status"] != "declined"]
    grid = {name: [] for name, _ in hub.TEN_TYPES}
    for iid, text, title in items:
        low = text.lower()
        placed = None
        for t, kws in _TYPE_KEYWORDS.items():
            if any(k in low for k in kws):
                placed = t
                break
        grid[placed or "Product Performance"].append(title[:60])
    out = [{"type": name, "about": desc, "count": len(grid[name]),
            "examples": grid[name][:3]} for name, desc in hub.TEN_TYPES]
    empties = [o["type"] for o in out if o["count"] == 0]
    return {"grid": out, "total": len(items), "empty_types": empties,
            "headline": (f"{len(items)} pipeline items concentrate in "
                         f"{10 - len(empties)} of the ten types — the empty ones "
                         f"({', '.join(empties[:4]) or 'none'}) are where defensibility lives."
                         if items else "No pipeline to mirror yet — seed or submit ideas first.")}


@app.get("/api/ideate/watchlist")
def competitive_watchlist() -> Dict[str, Any]:
    """Competitors as persistent watchlist: latest scan per topic plus what
    changed since the previous scan."""
    with_runs: Dict[str, List[Dict[str, Any]]] = {}
    from collections import defaultdict
    runs = defaultdict(list)
    # all competitive runs, oldest first
    with db._conn() as conn:
        rows = conn.execute("SELECT topic, output, created_at FROM studio_runs "
                            "WHERE kind='competitive' ORDER BY id").fetchall()
    import json as _json
    for r in rows:
        runs[r["topic"]].append({"created_at": r["created_at"],
                                 "output": _json.loads(r["output"])})
    cards = []
    for topic, rs in runs.items():
        latest, prev = rs[-1], (rs[-2] if len(rs) > 1 else None)
        new_items = []
        if prev:
            old_titles = {i["title"] for i in prev["output"].get("items", [])}
            new_items = [i["title"] for i in latest["output"].get("items", [])
                         if i["title"] not in old_titles]
        cards.append({"topic": topic, "last_scanned": latest["created_at"],
                      "scans": len(rs), "latest": latest["output"],
                      "changed_since_last": new_items})
    cards.sort(key=lambda c: c["last_scanned"], reverse=True)
    return {"watchlist": cards}


@app.get("/api/ideate/maturity-history")
def maturity_history(topic: str = Query(...)) -> Dict[str, Any]:
    with db._conn() as conn:
        rows = conn.execute("SELECT output, created_at FROM studio_runs "
                            "WHERE kind='maturity' AND topic=? ORDER BY id", (topic,)).fetchall()
    import json as _json, re as _re
    def levels(out):
        d = {}
        for it in out.get("items", []):
            m = _re.match(r"(.+?) — level (\d)/5", it["title"])
            if m:
                d[m.group(1)] = int(m.group(2))
        return d
    hist = [{"created_at": r["created_at"], "levels": levels(_json.loads(r["output"]))}
            for r in rows]
    deltas = {}
    if len(hist) > 1:
        prev, cur = hist[-2]["levels"], hist[-1]["levels"]
        deltas = {k: cur[k] - prev.get(k, cur[k]) for k in cur}
    return {"assessments": hist, "deltas": deltas}


@app.get("/api/ideate/sessions")
def workshop_sessions() -> Dict[str, Any]:
    """Past design-thinking sessions with their harvest results."""
    from collections import defaultdict
    import re as _re
    groups = defaultdict(list)
    for i in db.list_ideas():
        if i.get("source") != "mural":
            continue
        m = _re.search(r"session '([^']+)'", i.get("description") or "")
        groups[m.group(1) if m else "unnamed session"].append(i)
    out = []
    for name, ideas in groups.items():
        out.append({"session": name, "ideas": len(ideas),
                    "qualified": sum(1 for i in ideas if i["status"] not in ("proposed", "declined")),
                    "est_value": round(sum(i.get("estimated_annual_benefit")
                                           or (i.get("assessment") or {}).get("estimated_annual_benefit") or 0
                                           for i in ideas), 2)})
    return {"sessions": out}


@app.get("/api/ideate/studio/latest")
def latest_studio(kind: str = Query(...)) -> Dict[str, Any]:
    return {"run": db.latest_studio_run(kind)}


_MURAL_TEMPLATES = [
    ("Empathy map", "https://www.mural.co/templates/empathy-map"),
    ("Customer journey map", "https://www.mural.co/templates/customer-journey-map"),
    ("Brainwriting", "https://www.mural.co/templates/brainwriting"),
    ("Design sprint", "https://www.mural.co/templates/design-sprint"),
    ("Retrospective", "https://www.mural.co/templates/retrospective"),
    ("Mind map", "https://www.mural.co/templates/mind-map"),
    ("Browse all templates", "https://www.mural.co/templates"),
]


@app.get("/api/ideate/mural-templates")
def mural_templates() -> Dict[str, Any]:
    return {"templates": [{"name": n, "url": u} for n, u in _MURAL_TEMPLATES],
            "how": "Run the session in Mural, export sticky notes as text/CSV, then paste "
                   "them below — each line becomes a triaged idea."}


class MuralIngestRequest(BaseModel):
    text: str
    facilitator: Optional[str] = None
    session_name: Optional[str] = None


@app.post("/api/ideate/mural-ingest")
def mural_ingest(body: MuralIngestRequest) -> Dict[str, Any]:
    """Ingest a design-thinking session export: each non-trivial line becomes
    a real idea, triaged like any other."""
    lines = [ln.strip().strip('-•"') .strip() for ln in body.text.splitlines()]
    lines = [ln for ln in lines if len(ln) >= 12][:30]
    if not lines:
        raise HTTPException(400, "no usable lines — paste the sticky-note export text")
    created = []
    for ln in lines:
        idea = _ingest_idea(IdeaRequest(
            title=ln[:120],
            description=f"{ln} (from design-thinking session"
                        + (f" '{body.session_name}'" if body.session_name else "") + ")",
            submitter=body.facilitator), source="mural")
        created.append({"id": idea["id"], "title": idea["title"],
                        "recommendation": (idea.get("assessment") or {}).get("recommendation")})
    db.audit("ideate.mural_ingest", body.facilitator, None,
             f"{len(created)} ideas from '{body.session_name or 'session'}'")
    return {"created": created}


@app.get("/api/value-ledger")
def value_ledger(format: str = Query("json")) -> Any:
    """The Verified Value Ledger: every verified dollar traceable to a frozen
    baseline, a data source, and observation dates. This is the audit trail
    self-reported dashboards cannot produce."""
    rows = []
    for c in db.list_business_cases():
        for b in c.get("metric_bindings", []):
            observations = b.get("observations", [])
            rows.append({
                "case_id": c["id"], "case_title": c["title"],
                "metric": b["label"], "unit": b["unit"],
                "baseline_value": b["baseline_value"],
                "baseline_frozen_at": b["baseline_captured_at"],
                "latest_value": b.get("latest_value"),
                "last_observed_at": observations[-1]["observed_at"] if observations else None,
                "observations": len(observations),
                "verified_annual_value": b.get("annualized_delta"),
            })
    if format == "csv":
        from fastapi.responses import PlainTextResponse
        cols = ["case_id", "case_title", "metric", "unit", "baseline_value",
                "baseline_frozen_at", "latest_value", "last_observed_at",
                "observations", "verified_annual_value"]
        lines = [",".join(cols)]
        for r in rows:
            lines.append(",".join(f'"{str(r[c]) if r[c] is not None else ""}"' for c in cols))
        return PlainTextResponse("\n".join(lines), media_type="text/csv",
                                 headers={"Content-Disposition":
                                          "attachment; filename=value-ledger.csv"})
    total = round(sum(r["verified_annual_value"] or 0 for r in rows), 2)
    return {"entries": rows, "total_verified_annual_value": total}


@app.get("/api/benchmarks")
def benchmarks() -> Dict[str, Any]:
    """Calibration-derived benchmarks: how much of claimed value each category
    historically realizes — the honesty layer, exposed."""
    return {"categories": calibration.report()["categories"],
            "note": "applied_factor is the clamped realization multiplier used "
                    "in prioritization; it is learned from actuals, not assumed."}


# ------------------------------------- daily-ops UX: attachments, similar, search,
# ------------------------------------- reviews, notification settings, my work

@app.post("/api/ideas/{idea_id}/attachments")
async def upload_attachment(idea_id: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    if db.get_idea(idea_id) is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "attachments are limited to 5 MB")
    att = db.add_attachment("idea", idea_id, file.filename or "attachment",
                            file.content_type, data, _session_name())
    db.audit("idea.attach", _session_name(), idea_id, att["filename"])
    return att


@app.get("/api/ideas/{idea_id}/attachments")
def idea_attachments(idea_id: str) -> Dict[str, Any]:
    return {"attachments": db.list_attachments("idea", idea_id)}


@app.get("/api/attachments/{attachment_id}")
def download_attachment(attachment_id: int) -> Any:
    from fastapi.responses import Response
    att = db.get_attachment(attachment_id)
    if att is None:
        raise HTTPException(404, "attachment not found")
    return Response(att["data"], media_type=att["content_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{att["filename"]}"'})


@app.get("/api/ideas/similar")
def similar_ideas(q: str = Query(...)) -> Dict[str, Any]:
    """Pre-submission duplicate surfacing: as-you-type similarity so people
    join existing ideas instead of resubmitting them."""
    tokens = hub._tokens(q)
    if not tokens:
        return {"similar": []}
    scored = []
    for i in db.list_ideas():
        if i["status"] == "declined":
            continue
        overlap = len(tokens & hub._tokens(f"{i['title']} {i['description']}"))
        if overlap >= 2:
            scored.append((overlap, i))
    scored.sort(key=lambda t: -t[0])
    return {"similar": [
        {"id": i["id"], "title": i["title"], "status": i["status"],
         "submitter": i.get("submitter"), "vote_count": i.get("vote_count", 0)}
        for _, i in scored[:3]]}


@app.get("/api/search")
def global_search(q: str = Query(...)) -> Dict[str, Any]:
    ql = q.strip().lower()
    if len(ql) < 2:
        return {"results": []}
    results = []
    for i in db.list_ideas():
        if ql in i["title"].lower() or ql in (i.get("description") or "").lower():
            results.append({"type": "idea", "tab": "ideas", "id": i["id"],
                            "title": i["title"], "hint": i["status"]})
    for c in db.list_business_cases():
        if ql in c["title"].lower():
            results.append({"type": "case", "tab": "tracking", "id": c["id"],
                            "title": c["title"], "hint": c["stage"]})
    for o in _prioritized_opps():
        if ql in o["title"].lower() or ql in o["category"].lower():
            results.append({"type": "opportunity", "tab": "opportunities", "id": o["id"],
                            "title": o["title"],
                            "hint": f"${o['estimated_annual_savings']:,.0f}/yr"})
    return {"results": results[:12]}


class ReviewRequest(BaseModel):
    reviewer: str
    scores: Dict[str, int]
    comment: Optional[str] = None


@app.post("/api/ideas/{idea_id}/reviews")
def review_idea(idea_id: str, body: ReviewRequest) -> Dict[str, Any]:
    if db.get_idea(idea_id) is None:
        raise HTTPException(404, f"Idea '{idea_id}' not found")
    blocked = hub.check_role("reviewer", _session_name() or body.reviewer)
    if blocked:
        raise HTTPException(403, blocked)
    if not body.scores or any(not (1 <= v <= 5) for v in body.scores.values()):
        raise HTTPException(400, "scores must rate each criterion 1-5")
    db.save_review(idea_id, _session_name() or body.reviewer, body.scores, body.comment)
    db.audit("idea.review", _session_name() or body.reviewer, idea_id)
    return {"summary": db.review_summary(idea_id),
            "reviews": db.reviews_for(idea_id)}


@app.get("/api/settings/notifications")
def get_notification_settings() -> Dict[str, Any]:
    return {"webhook": db.meta_get("notify_webhook") or ""}


@app.put("/api/settings/notifications")
def put_notification_settings(body: Dict[str, str],
                              authorization: Optional[str] = Header(None),
                              actor: Optional[str] = Query(None)) -> Dict[str, Any]:
    _require_admin(authorization, actor)
    url = (body.get("webhook") or "").strip()
    if url and not url.startswith("https://"):
        raise HTTPException(400, "webhook must be an https:// URL")
    db.meta_set("notify_webhook", url)
    return {"webhook": url}


@app.get("/api/my-work")
def my_work(user: str = Query(...)) -> Dict[str, Any]:
    """The personal inbox: everything awaiting THIS person's action, with age.
    Reviewers see gate queues they can act on; submitters see their items
    needing response."""
    from datetime import datetime, timezone
    who = user.strip().lower()
    role = db.get_role(who)
    items = []

    def _age(ts):
        try:
            then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            return max(int((datetime.now(timezone.utc) - then).days), 0)
        except (ValueError, AttributeError):
            return 0

    # my submissions needing my response
    for i in db.list_ideas():
        if (i.get("submitter") or "").strip().lower() != who:
            continue
        history = db.events_for("idea", i["id"])
        if (history and history[-1]["action"] == "feedback") or            (i.get("assessment") or {}).get("recommendation") == "needs_info":
            items.append({"kind": "respond", "id": i["id"], "title": i["title"],
                          "tab": "mine", "age_days": _age(i["submitted_at"]),
                          "what": "Reviewers asked for more information"})
    # decisions I can make (open mode: everyone; else by role)
    can_review = role in (None, "reviewer", "executive", "admin")
    if can_review:
        steps = hub.get_workflow()
        for step in steps:
            for i in db.list_ideas():
                if i["status"] == step["key"]:
                    items.append({"kind": "decide", "id": i["id"], "title": i["title"],
                                  "tab": "command", "age_days": _age(i["submitted_at"]),
                                  "what": f"Awaiting {step['gate']}"})
    if role in (None, "executive", "admin"):
        for c in db.list_business_cases():
            if c["stage"] in ("draft", "proposed"):
                items.append({"kind": "decide", "id": c["id"], "title": c["title"],
                              "tab": "command", "age_days": _age(c["submitted_at"]),
                              "what": "Business case awaiting executive review"})
    items.sort(key=lambda x: -x["age_days"])
    return {"items": items[:15], "role": role}


# --------------------------------- compelling capabilities: P&L, delay, red team,
# --------------------------------- simulator, genome, dividends, signal radar

@app.get("/api/reports/innovation-pnl")
def innovation_pnl() -> Dict[str, Any]:
    """The Innovation P&L: a CFO-signable statement. Capital deployed is real
    (released tranches), returns are verified (computed from data), the
    forecast book is calibration-adjusted, and kills are carried as tuition
    with their learnings as the asset."""
    cases = db.list_business_cases()
    factors = calibration.factors()
    deployed = sum((c.get("funding") or {}).get("released", 0) for c in cases)
    verified = sum((b.get("annualized_delta") or 0)
                   for c in cases for b in c.get("metric_bindings", []))
    claimed = sum(e["amount"] for c in cases for e in c.get("savings_entries", []))
    forecast_raw, forecast_calibrated = 0.0, 0.0
    for c in cases:
        if c["stage"] in ("proposed", "experiment", "approved", "in_delivery"):
            est = c.get("estimated_annual_benefit") or 0
            if not est and c.get("linked_opportunity"):
                est = c["linked_opportunity"].get("estimated_annual_savings") or 0
            forecast_raw += est
            cat = (c.get("linked_opportunity") or {}).get("category", "")
            forecast_calibrated += est * factors.get(cat, 0.7)
    tuition = [{"case_id": c["id"], "title": c["title"],
                "cost": sum(e.get("cost") or 0 for e in c.get("experiments", [])),
                "learning": next((e["learnings"] for e in c.get("experiments", [])
                                  if e.get("outcome") == "kill"), None)}
               for c in cases
               if any(e.get("outcome") == "kill" for e in c.get("experiments", []))]
    return {
        "capital_deployed": round(deployed, 2),
        "verified_annual_return": round(verified, 2),
        "claimed_savings_to_date": round(claimed, 2),
        "forecast_book_raw": round(forecast_raw, 2),
        "forecast_book_calibrated": round(forecast_calibrated, 2),
        "tuition_paid": round(sum(t["cost"] for t in tuition), 2),
        "tuition_lessons": tuition,
        "note": "verified and claimed are never blended; the calibrated forecast "
                "applies realization factors learned from actuals",
    }


def _cost_of_delay(ideas: List[Dict[str, Any]]) -> Dict[str, Any]:
    from datetime import datetime, timezone
    total, rows = 0.0, []
    now = datetime.now(timezone.utc)
    for i in ideas:
        est = (i.get("estimated_annual_benefit")
               or ((i.get("assessment") or {}).get("matched_opportunity") or {})
               .get("estimated_annual_savings") or 0)
        if not est:
            continue
        try:
            then = datetime.fromisoformat(i["submitted_at"].replace("Z", "+00:00"))
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            days = max((now - then).days, 0)
        except (ValueError, KeyError):
            days = 0
        burned = est / 365.0 * days
        total += burned
        rows.append({"id": i["id"], "title": i["title"], "days_waiting": days,
                     "burned": round(burned, 2)})
    rows.sort(key=lambda r: -r["burned"])
    return {"total_burned": round(total, 2), "items": rows[:10]}


@app.post("/api/business-cases/{case_id}/redteam")
def red_team(case_id: str) -> Dict[str, Any]:
    """Adversarial pre-mortem: the case for why this will fail, generated
    before executives see the advocate's plan."""
    case = db.get_business_case(case_id)
    if case is None:
        raise HTTPException(404, f"Business case '{case_id}' not found")
    memo = hub.red_team_case(case)
    db.set_red_team(case_id, memo)
    db.audit("case.redteam", _session_name(), case_id)
    return {"red_team": memo}


class SimulationRequest(BaseModel):
    case_ids: Optional[List[str]] = None
    trials: int = 2000


@app.post("/api/simulator")
def portfolio_simulator(body: SimulationRequest) -> Dict[str, Any]:
    """Monte Carlo over the funding decision, sampling realization from the
    calibration layer: probability-weighted outcomes, not point estimates."""
    import random
    factors = calibration.factors()
    cases = [c for c in db.list_business_cases()
             if c["stage"] in ("proposed", "experiment", "approved", "in_delivery")
             and (not body.case_ids or c["id"] in body.case_ids)]
    if not cases:
        return {"cases": 0, "note": "no active cases to simulate"}
    trials = max(200, min(body.trials, 10000))
    totals = []
    per_case = {c["id"]: [] for c in cases}
    for _ in range(trials):
        run = 0.0
        for c in cases:
            est = (c.get("estimated_annual_benefit")
                   or (c.get("linked_opportunity") or {}).get("estimated_annual_savings") or 0)
            cat = (c.get("linked_opportunity") or {}).get("category", "")
            f = factors.get(cat, 0.7)
            # triangular around the learned factor: pessimist half, optimist +20%
            sampled = est * random.triangular(f * 0.5, min(f * 1.2, 1.0), f)
            cost = (c.get("funding") or {}).get("planned", 0) or est * 0.3
            run += sampled - cost * 0.2  # annualized cost share
            per_case[c["id"]].append(sampled)
        totals.append(run)
    totals.sort()
    pct = lambda p: round(totals[int(p / 100 * (trials - 1))], 2)
    return {
        "cases": len(cases), "trials": trials,
        "annual_value_p10": pct(10), "annual_value_p50": pct(50), "annual_value_p90": pct(90),
        "probability_positive": round(sum(1 for t in totals if t > 0) / trials, 3),
        "per_case": [{"id": cid, "title": next(c["title"] for c in cases if c["id"] == cid),
                      "p50": round(sorted(v)[len(v) // 2], 2)}
                     for cid, v in per_case.items()],
        "note": "realization sampled from calibration factors learned from actuals",
    }


@app.get("/api/genome")
def innovation_genome() -> Dict[str, Any]:
    """What predicts success at THIS company: promotion-rate multipliers per
    intake trait, learned from our own history. Low samples are flagged, not
    hidden."""
    ideas = db.list_ideas()
    if len(ideas) < 4:
        return {"traits": [], "note": "not enough history yet — keep shipping"}
    def promoted(i):
        return i["status"] == "business_case"
    base = sum(1 for i in ideas if promoted(i)) / len(ideas) or 0.0001
    traits = [
        ("Named beneficiary", lambda i: bool(i.get("beneficiary"))),
        ("Quantified benefit at intake", lambda i: bool(i.get("estimated_annual_benefit"))),
        ("Tagged to a strategic objective", lambda i: bool(i.get("initiative_ids"))),
        ("Answers a challenge", lambda i: bool(i.get("challenge_id"))),
        ("Peer votes", lambda i: (i.get("vote_count") or 0) > 0),
        ("Named pain point", lambda i: bool(i.get("pain_point"))),
    ]
    out = []
    for label, pred in traits:
        cohort = [i for i in ideas if pred(i)]
        if not cohort:
            continue
        rate = sum(1 for i in cohort if promoted(i)) / len(cohort)
        out.append({"trait": label, "sample": len(cohort),
                    "promotion_rate": round(rate, 3),
                    "multiplier": round(rate / base, 2),
                    "low_confidence": len(cohort) < 8})
    out.sort(key=lambda t: -t["multiplier"])
    return {"baseline_promotion_rate": round(base, 3), "ideas": len(ideas), "traits": out}


@app.get("/api/learning-dividends")
def get_learning_dividends() -> Dict[str, Any]:
    return {"dividends": db.learning_dividends()}


class RadarRequest(BaseModel):
    topic: str
    launch: bool = False


@app.post("/api/radar/scan")
def signal_radar(body: RadarRequest) -> Dict[str, Any]:
    """Signal-to-sprint: research a topic/competitor and draft a targeted
    challenge with starter ideas. AI+web when a key is set; template signals
    otherwise."""
    if not body.topic.strip():
        raise HTTPException(400, "a topic (competitor, trend, or market) is required")
    draft = hub.radar_scan(body.topic.strip())
    challenge = None
    if body.launch:
        challenge = create_challenge(ChallengeRequest(
            title=draft["challenge_title"], question=draft["challenge_question"],
            theme=draft.get("theme")))
        db.audit("radar.launch", _session_name(), challenge["id"], body.topic)
    return {"challenge": challenge, "draft": draft, "signals": draft["signals"],
            "starter_ideas": draft["starter_ideas"], "generated_by": draft["generated_by"]}


# ------------------------------------------------- full-lifecycle sample data

@app.post("/api/demo/seed-lifecycle")
def seed_lifecycle(force: bool = Query(False)) -> Dict[str, Any]:
    """Populate every phase of the lifecycle with realistic sample content so
    the full look and feel is visible: ideas at each gate, cases at each stage,
    an experiment kill with learnings, funding tranches, claimed savings and
    KPI readings, plus a real measured reduction observed from changed data."""
    from datetime import datetime, timedelta

    if (db.list_ideas() and not db.meta_get("seeded_lifecycle") and not force):
        raise HTTPException(409, "This hub already has real ideas in it — seeding would "
                                 "replace them. Pass ?force=true only if that's intended.")
    load_samples()
    days = lambda n: (datetime.utcnow() - timedelta(days=n)).isoformat()

    inits = [db.create_initiative(n, o) for n, o in [
        ("Cost & efficiency", "Cut run-rate cost of operations by 15%"),
        ("Customer experience", "Halve time-to-resolution for customer issues"),
        ("AI-first operations", "Automate the top 20 manual back-office workflows"),
    ]]
    challenge = create_challenge(ChallengeRequest(
        title="Cut cost-to-serve in half",
        question="Where do we spend people-hours that a customer would never pay for?",
        theme="cost"))

    def idea(title, desc, who, benefit=None, days_ago=0, init=None, chal=None,
             beneficiary=None, pain=None):
        return _ingest_idea(IdeaRequest(
            title=title, description=desc, submitter=who,
            estimated_annual_benefit=benefit,
            initiative_ids=[init["id"]] if init else None,
            challenge_id=chal, beneficiary=beneficiary, pain_point=pain,
        ), source="manual", submitted_at=days(days_ago))

    def walk(i, *decisions, actor="rio"):
        for d in decisions:
            result = command_decide(DecisionRequest(
                subject_type="idea", subject_id=i["id"], decision=d, actor=actor))
        return result["result"].get("case") or db.get_idea(i["id"])

    # --- ideation: one idea resting at every gate ---
    fresh = idea("Digital mailroom with OCR routing",
                 "Physical mail is opened, scanned, and routed by hand today.",
                 "priya", 60000, 1, inits[2])
    needs_info = idea("Better reporting", "We should improve reports.", "sam", None, 2)
    command_decide(DecisionRequest(subject_type="idea", subject_id=needs_info["id"],
                                   decision="feedback", actor="rio",
                                   comment="Which reports, for whom, and what decision do they drive?"))
    qualified = idea("Self-service password resets",
                     "Password resets are 30% of service-desk tickets; a self-service flow "
                     "with MFA removes the wait for employees and frees agents.",
                     "alex", 90000, 9, inits[0], beneficiary="Service-desk agents",
                     pain="Repetitive resets crowd out real incidents")
    walk(qualified, "qualify")
    prioritized = idea("Right-size over-provisioned VMs",
                       "Cloud spend grows 8% a quarter while average utilization sits under "
                       "20%; automated right-sizing recommendations reviewed weekly.",
                       "jordan", 150000, 14, inits[0], chal=challenge["id"])
    walk(prioritized, "qualify", "prioritize")
    held = idea("Office plant subscription",
                "Plants improve morale and air quality across our five offices.",
                "sam", None, 20)
    walk(held, "qualify")
    command_decide(DecisionRequest(subject_type="idea", subject_id=held["id"],
                                   decision="hold", actor="rio",
                                   comment="Nice-to-have; revisit next quarter"))
    rejected = idea("Rewrite everything in Rust", "It would be faster.", "sam", None, 21)
    command_decide(DecisionRequest(subject_type="idea", subject_id=rejected["id"],
                                   decision="reject", actor="rio",
                                   comment="No measurable business outcome stated"))
    for who in ("alex", "jordan", "maria"):
        vote_idea(qualified["id"], VoteRequest(voter=who))
    add_comment(prioritized["id"], CommentRequest(
        author="maria", comment="Finance would co-sponsor this — the quarterly true-up is painful.",
        build_on=True))

    # --- business case & funding ---
    exec_review = walk(idea("Automate invoice matching",
                            "Three-way matching is manual for 40% of invoices; exceptions "
                            "queue for days and suppliers chase payment status by phone.",
                            "priya", 220000, 30, inits[0]),
                       "qualify", "prioritize", "develop")
    experimenting = walk(idea("AI triage for support tickets",
                              "Classify and route inbound tickets so specialists stop "
                              "hand-sorting the queue every morning.",
                              "alex", 180000, 35, inits[1]),
                         "qualify", "prioritize", "develop")
    add_experiment(experimenting["id"], ExperimentRequest(
        hypothesis="A classifier on 12 months of tickets routes ≥80% correctly",
        method="Shadow-route two weeks of live tickets; compare against agents",
        success_criteria="≥80% routing accuracy, no P1 misroutes", cost=8000))
    killed = walk(idea("Chatbot for all HR questions",
                       "Answer every HR policy question with a chatbot.",
                       "sam", 120000, 40, inits[2]),
                  "qualify", "prioritize", "develop")
    exp = add_experiment(killed["id"], ExperimentRequest(
        hypothesis="Employees will accept chatbot answers for sensitive HR topics",
        method="Pilot with 50 employees for two weeks",
        success_criteria="CSAT ≥ 4.0 and ≤10% escalation", cost=5000))
    conclude_experiment(killed["id"], exp["experiments"][-1]["id"],
                        ConcludeExperimentRequest(
        outcome="kill",
        learnings="People will not discuss leave, pay, or grievances with a bot; trust, "
                  "not accuracy, was the barrier. Narrow FAQ automation works — "
                  "sensitive topics need a human."))
    approved = walk(idea("Decommission idle cloud instances",
                         "Dozens of instances idle below 5% CPU around the clock; "
                         "schedule or decommission them with owner sign-off.",
                         "jordan", 200000, 45, inits[0], chal=challenge["id"]),
                    "qualify", "prioritize", "develop")
    command_decide(DecisionRequest(subject_type="case", subject_id=approved["id"],
                                   decision="approve", actor="eve",
                                   comment="Strong payback; fund discovery tranche"))
    add_tranche(approved["id"], TrancheRequest(label="Discovery", amount=15000,
                                               milestone="Owner sign-off on top 20 instances"))
    add_tranche(approved["id"], TrancheRequest(label="Rollout", amount=45000,
                                               milestone="First 10 instances decommissioned"))
    case = db.get_business_case(approved["id"])
    release_tranche(approved["id"], case["funding"]["tranches"][0]["id"], ReleaseRequest(actor="eve"))

    def approved_case(title, desc, who, benefit, days_ago, init):
        c = walk(idea(title, desc, who, benefit, days_ago, init),
                 "qualify", "prioritize", "develop")
        command_decide(DecisionRequest(subject_type="case", subject_id=c["id"],
                                       decision="approve", actor="eve"))
        add_tranche(c["id"], TrancheRequest(label="Delivery", amount=60000,
                                            milestone="Go-live"))
        cc = db.get_business_case(c["id"])
        release_tranche(c["id"], cc["funding"]["tranches"][0]["id"], ReleaseRequest(actor="eve"))
        return c

    # --- delivery & value ---
    delivering = approved_case("Robotic process automation for order entry",
                               "Manual re-keying of orders from email into the ERP "
                               "consumes four FTEs and introduces errors.",
                               "priya", 260000, 60, inits[2])
    db.set_stage(delivering["id"], "in_delivery")

    live = approved_case("Decommission idle cloud instances — wave 1",
                         "Instances idle below 5% CPU around the clock; wave 1 "
                         "decommissions the worst idle cloud resources with owner "
                         "sign-off.",
                         "alex", 170000, 90, inits[0])
    implement_case(live["id"], ImplementRequest(go_live_date=days(75)[:10]))  # pydantic coerces ISO strings
    for n, amt in ((70, 12000), (40, 14500), (10, 15200)):
        add_savings(live["id"], SavingsRequest(entry_date=days(n)[:10], amount=amt,
                                                  note="License true-down, monthly"))
    lv = db.get_business_case(live["id"])
    for k in lv["roi_plan"]["kpis"][:1]:
        for n, val in ((70, 310), (40, 240), (10, 195)):
            add_reading(live["id"], ReadingRequest(kpi_name=k["name"],
                                                      reading_date=days(n)[:10], value=val))

    realized = approved_case("Automated employee onboarding provisioning",
                             "Accounts, hardware, and access provisioned by checklist "
                             "over five days; automation cuts it to one.",
                             "maria", 140000, 120, inits[1])
    implement_case(realized["id"], ImplementRequest(go_live_date=days(100)[:10]))
    add_savings(realized["id"], SavingsRequest(entry_date=days(30)[:10], amount=38000,
                                                  note="Quarterly measure: onboarding hours"))
    db.set_stage(realized["id"], "value_realized")

    scaled = approved_case("Invoice OCR rollout — EU region",
                           "Replicate the proven invoice OCR pattern from North America "
                           "to the EU shared-service center.",
                           "priya", 190000, 150, inits[0])
    implement_case(scaled["id"], ImplementRequest(go_live_date=days(120)[:10]))
    add_savings(scaled["id"], SavingsRequest(entry_date=days(20)[:10], amount=52000,
                                                note="First-quarter measured run-rate"))
    db.set_stage(scaled["id"], "scale")

    # a real measured reduction: the fix was "implemented" (idle instances
    # actually removed from the customer's data), then we re-observe every
    # frozen baseline — verified value is computed, never typed
    rows = _loaded_datasets().get("cloud", [])
    if rows:
        def _cpu(r):
            try:
                return float(r.get("avg_cpu_pct") or 100)
            except (TypeError, ValueError):
                return 100.0
        idle_rows = [r for r in rows if _cpu(r) < 5.0]
        gone = {id(r) for r in idle_rows[: max(2, len(idle_rows) - 1)]}
        db.save_dataset("cloud", [r for r in rows if id(r) not in gone],
                        origin="sample (post-implementation)")
    for c in db.list_business_cases():
        for b in c.get("metric_bindings", []):
            try:
                observe_binding(c["id"], b["id"])
            except Exception:
                pass
    # ideate studios: a sample run per capability so every tab lands populated
    for kind, topic, hz in [
        ("futures", "Autonomous field operations", "7-15y"),
        ("competitive", "ServiceNow expanding into our category", "3-7y"),
        ("maturity", "AI-driven operations", "3-7y"),
        ("ten_types", "Field service", "3-7y"),
    ]:
        db.save_studio_run(kind, topic, hz, hub.ideate_studio(kind, topic, hz))
    mural_ingest(MuralIngestRequest(
        text="Predictive parts stocking from telemetry\n"
             "One-tap warranty claims for technicians\n"
             "Customer-visible repair progress tracker",
        session_name="Q3 design sprint", facilitator="maria"))
    db.meta_set("seeded_lifecycle", days(0))

    return {
        "seeded": True,
        "ideas": len(db.list_ideas()),
        "cases": len(db.list_business_cases()),
        "initiatives": len(inits),
        "note": "Sample content across every lifecycle phase; use Demo Studio revert "
                "or reload samples to reset.",
    }
