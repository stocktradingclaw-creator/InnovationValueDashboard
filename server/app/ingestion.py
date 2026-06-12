"""CSV ingestion for the four supported source types.

Each source type declares the columns it needs and how to coerce them.
Extra columns are kept as-is so customers can bring richer exports.
"""
import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).strip().replace("$", "").replace(",", "")
    if cleaned == "":
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # tolerate datetime strings like "2026-01-02 03:04:05" / ISO timestamps
    text = text.split("T")[0].split(" ")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _to_str(value: Any) -> str:
    return ("" if value is None else str(value)).strip()


SOURCE_TYPES: Dict[str, Dict[str, Any]] = {
    "cmdb": {
        "label": "CMDB export (ServiceNow-style)",
        "required": ["ci_name", "ci_type", "status", "environment", "annual_cost"],
        "coerce": {
            "annual_cost": _to_float,
            "cpu_utilization_pct": _to_float,
            "eol_date": _to_date,
        },
    },
    "erp": {
        "label": "ERP financials (SAP-style)",
        "required": ["invoice_id", "vendor", "category", "amount", "invoice_date"],
        "coerce": {
            "amount": _to_float,
            "invoice_date": _to_date,
            "payment_terms_days": _to_float,
        },
    },
    "cloud": {
        "label": "Cloud billing (AWS/Azure)",
        "required": ["resource_id", "service", "monthly_cost", "state"],
        "coerce": {
            "monthly_cost": _to_float,
            "avg_cpu_pct": _to_float,
        },
    },
    "itsm": {
        "label": "ITSM tickets",
        "required": ["ticket_id", "ticket_type", "category", "opened_at"],
        "coerce": {
            "opened_at": _to_date,
            "resolution_minutes": _to_float,
        },
    },
}


class IngestionError(ValueError):
    pass


def normalize_rows(source_type: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Coerce typed columns on rows that didn't come through parse_csv —
    rows loaded back from the database (dates are ISO strings there) or
    produced by a live connector."""
    spec = SOURCE_TYPES[source_type]
    normalized = []
    for row in rows:
        out = dict(row)
        for col, coercer in spec["coerce"].items():
            if col in out:
                out[col] = coercer(out[col])
        normalized.append(out)
    return normalized


def parse_csv(source_type: str, raw: bytes) -> List[Dict[str, Any]]:
    if source_type not in SOURCE_TYPES:
        raise IngestionError(f"Unknown source type '{source_type}'. Expected one of: {', '.join(SOURCE_TYPES)}")

    spec = SOURCE_TYPES[source_type]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestionError("File must be UTF-8 encoded CSV")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise IngestionError("CSV has no header row")

    headers = [h.strip().lower() for h in reader.fieldnames]
    missing = [col for col in spec["required"] if col not in headers]
    if missing:
        raise IngestionError(
            f"Missing required columns for {source_type}: {', '.join(missing)}. Found: {', '.join(headers)}"
        )

    rows: List[Dict[str, Any]] = []
    for raw_row in reader:
        row = {(k or "").strip().lower(): _to_str(v) for k, v in raw_row.items() if k}
        for col, coercer in spec["coerce"].items():
            if col in row:
                row[col] = coercer(row[col])
        rows.append(row)

    if not rows:
        raise IngestionError("CSV contained a header but no data rows")
    return rows
