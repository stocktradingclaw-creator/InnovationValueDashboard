"""InnovationValueDashboard API.

Run with:  uvicorn app.main:app --reload --port 8000  (from the server/ directory)
"""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import (
    calibration, connectors, db, metrics, opportunities,
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


@app.get("/api/portfolio/diagnostic")
def portfolio_diagnostic() -> Dict[str, Any]:
    rows = normalize_rows("portfolio", db.load_dataset("portfolio"))
    if not rows:
        raise HTTPException(
            400, "No portfolio loaded — upload a PMO export to the 'portfolio' source first"
        )
    return portfolio.diagnose(rows)


@app.get("/api/dashboard")
def dashboard() -> Dict[str, Any]:
    """Everything an executive overview needs, in one call: the value funnel
    (identified -> risk-adjusted -> committed -> verified), opportunity mix,
    case pipeline, calibration quality, and data freshness."""
    result = prioritization.prioritize(_analyze(), None, calibration.factors())
    opps = result["opportunities"]
    cases = db.list_business_cases()
    meta = db.dataset_meta()

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

    return {
        "funnel": {
            "identified_annual_savings": round(identified, 2),
            "risk_adjusted_annual_savings": round(risk_adjusted, 2),
            "committed_annual_savings": round(committed, 2),
            "measured_annual_savings": round(measured, 2),
            "claimed_savings_to_date": round(claimed, 2),
        },
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
        "timeline": timeline.build(cases),
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
