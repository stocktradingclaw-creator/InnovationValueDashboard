"""Live source connectors.

Pulls data directly from customer systems instead of CSV exports and
normalizes it to the canonical schemas in ingestion.SOURCE_TYPES.

- ServiceNow: Table API (basic auth) for CMDB CIs and ITSM tickets.
- SAP: generic OData v2 JSON endpoint for invoice/financial line items.

Credentials are supplied per-sync request and never persisted. Field
mappings ship with sensible defaults but real instances usually customize
fields — every sync accepts a field_map override.
"""
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .ingestion import normalize_rows

TIMEOUT = 30.0


class ConnectorError(Exception):
    pass


def _display(value: Any) -> Any:
    """ServiceNow returns reference fields as {display_value, link} dicts."""
    if isinstance(value, dict):
        return value.get("display_value") or value.get("value") or ""
    return value


def _get_json(url: str, auth: Optional[Tuple[str, str]], params: Dict[str, Any]) -> Any:
    try:
        resp = httpx.get(url, auth=auth, params=params, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Could not reach {url}: {exc}")
    if resp.status_code == 401:
        raise ConnectorError("Authentication failed (401) — check username/password")
    if resp.status_code >= 400:
        raise ConnectorError(f"{url} returned HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return resp.json()
    except ValueError:
        raise ConnectorError(f"{url} did not return JSON (got: {resp.text[:200]}...)")


# ------------------------------------------------------------------ ServiceNow

DEFAULT_CMDB_MAP = {
    "ci_name": "name",
    "ci_type": "sys_class_name",
    "status": "install_status",
    "environment": "u_environment",
    "annual_cost": "cost",
    "cpu_utilization_pct": "u_cpu_utilization",
    "eol_date": "u_eol_date",
    "application_category": "u_application_category",
}

DEFAULT_INCIDENT_MAP = {
    "ticket_id": "number",
    "category": "category",
    "opened_at": "sys_created_on",
    "resolution_minutes": "calendar_stc",  # seconds; converted below
    "ci_name": "cmdb_ci",
}

DEFAULT_REQUEST_MAP = {
    "ticket_id": "number",
    "category": "cat_item",
    "opened_at": "sys_created_on",
    "resolution_minutes": "calendar_stc",
    "ci_name": "cmdb_ci",
}


def _servicenow_table(
    instance_url: str,
    auth: Tuple[str, str],
    table: str,
    field_map: Dict[str, str],
    limit: int,
) -> List[Dict[str, Any]]:
    url = f"{instance_url.rstrip('/')}/api/now/table/{table}"
    data = _get_json(url, auth, {
        "sysparm_display_value": "true",
        "sysparm_limit": limit,
        "sysparm_fields": ",".join(sorted(set(field_map.values()))),
    })
    records = data.get("result")
    if records is None:
        raise ConnectorError(f"Unexpected ServiceNow response shape from {table}: no 'result' key")
    rows = []
    for rec in records:
        rows.append({target: _display(rec.get(source, "")) for target, source in field_map.items()})
    return rows


def sync_servicenow(
    instance_url: str,
    username: str,
    password: str,
    source: str,
    field_map: Optional[Dict[str, str]] = None,
    table: Optional[str] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """source: 'cmdb' pulls CIs; 'itsm' pulls incidents + service requests."""
    auth = (username, password)
    if source == "cmdb":
        rows = _servicenow_table(
            instance_url, auth, table or "cmdb_ci",
            field_map or DEFAULT_CMDB_MAP, limit,
        )
        return normalize_rows("cmdb", rows)

    if source == "itsm":
        incidents = _servicenow_table(
            instance_url, auth, "incident", field_map or DEFAULT_INCIDENT_MAP, limit,
        )
        for r in incidents:
            r["ticket_type"] = "Incident"
        requests_ = _servicenow_table(
            instance_url, auth, "sc_req_item", field_map or DEFAULT_REQUEST_MAP, limit,
        )
        for r in requests_:
            r["ticket_type"] = "Request"
        rows = incidents + requests_
        for r in rows:  # calendar_stc is in seconds
            secs = r.get("resolution_minutes")
            try:
                r["resolution_minutes"] = float(secs) / 60 if secs not in (None, "") else None
            except (TypeError, ValueError):
                r["resolution_minutes"] = None
        return normalize_rows("itsm", rows)

    raise ConnectorError(f"ServiceNow connector supports 'cmdb' or 'itsm', not '{source}'")


# ------------------------------------------------------------------------ SAP

DEFAULT_SAP_MAP = {
    "invoice_id": "InvoiceDocNumber",
    "vendor": "SupplierName",
    "category": "PurchasingGroupName",
    "amount": "GrossAmount",
    "invoice_date": "DocumentDate",
    "payment_terms_days": "PaymentTermsDays",
    "po_number": "PurchaseOrder",
}

_ODATA_DATE = re.compile(r"/Date\((\d+)([+-]\d+)?\)/")


def _odata_value(value: Any) -> Any:
    """SAP OData v2 serializes dates as /Date(epoch_ms)/ — convert to ISO."""
    if isinstance(value, str):
        m = _ODATA_DATE.match(value)
        if m:
            return datetime.fromtimestamp(
                int(m.group(1)) / 1000, tz=timezone.utc
            ).date().isoformat()
    return value


def sync_sap_odata(
    service_url: str,
    entity_set: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    field_map: Optional[Dict[str, str]] = None,
    limit: int = 10000,
) -> List[Dict[str, Any]]:
    """Pull invoice line items from an SAP OData v2 service into the erp schema."""
    auth = (username, password) if username else None
    url = f"{service_url.rstrip('/')}/{entity_set}"
    data = _get_json(url, auth, {"$format": "json", "$top": limit})

    # OData v2 wraps results in {"d": {"results": [...]}} ; v4 uses {"value": [...]}
    if isinstance(data, dict) and "d" in data:
        records = data["d"].get("results", data["d"])
    elif isinstance(data, dict) and "value" in data:
        records = data["value"]
    else:
        raise ConnectorError("Unexpected OData response shape: expected 'd.results' or 'value'")
    if not isinstance(records, list):
        raise ConnectorError("OData response did not contain a list of records")

    mapping = field_map or DEFAULT_SAP_MAP
    rows = []
    for rec in records:
        rows.append({target: _odata_value(rec.get(source, "")) for target, source in mapping.items()})
    return normalize_rows("erp", rows)
