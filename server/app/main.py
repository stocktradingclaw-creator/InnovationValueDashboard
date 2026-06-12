"""InnovationValueDashboard API.

Run with:  uvicorn app.main:app --reload --port 8000  (from the server/ directory)
"""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import connectors, db, opportunities, roi
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
def get_opportunities() -> Dict[str, Any]:
    opps = _analyze()
    return {
        "opportunities": opps,
        "total_estimated_annual_savings": round(
            sum(o["estimated_annual_savings"] for o in opps), 2
        ),
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
    return db.create_business_case(
        title=body.title.strip(),
        description=body.description.strip(),
        estimated_cost=body.estimated_cost,
        roi_plan=result["plan"],
        generated_by=result["generated_by"],
        note=result["note"],
        linked_opportunity=linked_opportunity,
    )


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
