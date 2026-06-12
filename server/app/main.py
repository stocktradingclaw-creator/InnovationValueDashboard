"""InnovationValueDashboard API.

Run with:  uvicorn app.main:app --reload --port 8000  (from the server/ directory)
"""
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import opportunities, roi, store
from .ingestion import SOURCE_TYPES, IngestionError, parse_csv

app = FastAPI(title="InnovationValueDashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def _json_safe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    safe = []
    for row in rows:
        safe.append({
            k: (v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v)
            for k, v in row.items()
        })
    return safe


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/datasets")
def list_datasets() -> Dict[str, Any]:
    return {
        "sources": [
            {
                "source_type": st,
                "label": spec["label"],
                "required_columns": spec["required"],
                "rows_loaded": len(store.datasets.get(st, [])),
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
        store.datasets[source_type] = parse_csv(source_type, path.read_bytes())
        loaded[source_type] = len(store.datasets[source_type])
    return {"loaded": loaded}


@app.post("/api/datasets/{source_type}")
async def upload_dataset(source_type: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    raw = await file.read()
    try:
        rows = parse_csv(source_type, raw)
    except IngestionError as exc:
        raise HTTPException(400, str(exc))
    store.datasets[source_type] = rows
    return {"source_type": source_type, "rows_loaded": len(rows)}


@app.delete("/api/datasets/{source_type}")
def clear_dataset(source_type: str) -> Dict[str, Any]:
    if source_type not in SOURCE_TYPES:
        raise HTTPException(404, f"Unknown source type '{source_type}'")
    store.datasets.pop(source_type, None)
    return {"source_type": source_type, "rows_loaded": 0}


@app.get("/api/opportunities")
def get_opportunities() -> Dict[str, Any]:
    if not any(store.datasets.values()):
        return {"opportunities": [], "total_estimated_annual_savings": 0.0}
    opps = opportunities.analyze()
    return {
        "opportunities": opps,
        "total_estimated_annual_savings": round(
            sum(o["estimated_annual_savings"] for o in opps), 2
        ),
    }


class BusinessCaseRequest(BaseModel):
    title: str
    description: str
    estimated_cost: Optional[float] = None


@app.post("/api/business-cases")
def create_business_case(body: BusinessCaseRequest) -> Dict[str, Any]:
    if not body.title.strip() or not body.description.strip():
        raise HTTPException(400, "title and description are required")
    result = roi.generate_roi_plan(body.title.strip(), body.description.strip(), body.estimated_cost)
    case = {
        "id": store.next_id("BC"),
        "title": body.title.strip(),
        "description": body.description.strip(),
        "estimated_cost": body.estimated_cost,
        "submitted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "roi_plan": result["plan"],
        "generated_by": result["generated_by"],
        "note": result["note"],
    }
    store.business_cases.append(case)
    return case


@app.get("/api/business-cases")
def list_business_cases() -> Dict[str, Any]:
    return {"business_cases": list(reversed(store.business_cases))}
