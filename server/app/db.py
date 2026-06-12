"""SQLite persistence layer.

Replaces the in-memory store: datasets, business cases, KPI readings, and
realized-savings entries survive server restarts. The DB path can be
overridden with the IVD_DB_PATH env var (used by tests).
"""
import datetime
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    source_type TEXT PRIMARY KEY,
    rows_json   TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    origin      TEXT NOT NULL DEFAULT 'csv',
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_cases (
    id                      TEXT PRIMARY KEY,
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    estimated_cost          REAL,
    submitted_at            TEXT NOT NULL,
    roi_plan_json           TEXT NOT NULL,
    generated_by            TEXT NOT NULL,
    note                    TEXT,
    linked_opportunity_json TEXT,
    status                  TEXT NOT NULL DEFAULT 'proposed',
    go_live_date            TEXT
);
CREATE TABLE IF NOT EXISTS kpi_readings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id      TEXT NOT NULL REFERENCES business_cases(id),
    kpi_name     TEXT NOT NULL,
    reading_date TEXT NOT NULL,
    value        REAL NOT NULL,
    note         TEXT
);
CREATE TABLE IF NOT EXISTS savings_entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL REFERENCES business_cases(id),
    entry_date TEXT NOT NULL,
    amount     REAL NOT NULL,
    note       TEXT
);
"""


def _db_path() -> str:
    return os.environ.get(
        "IVD_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data.db"),
    )


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _json_safe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    safe = []
    for row in rows:
        safe.append({
            k: (v.isoformat() if isinstance(v, (datetime.date, datetime.datetime)) else v)
            for k, v in row.items()
        })
    return safe


# ------------------------------------------------------------------ datasets

def save_dataset(source_type: str, rows: List[Dict[str, Any]], origin: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO datasets (source_type, rows_json, row_count, origin, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(source_type) DO UPDATE SET rows_json=excluded.rows_json, "
            "row_count=excluded.row_count, origin=excluded.origin, updated_at=excluded.updated_at",
            (source_type, json.dumps(_json_safe(rows)), len(rows), origin, _now()),
        )


def load_dataset(source_type: str) -> List[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT rows_json FROM datasets WHERE source_type = ?", (source_type,)
        ).fetchone()
    return json.loads(row["rows_json"]) if row else []


def dataset_meta() -> Dict[str, Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT source_type, row_count, origin, updated_at FROM datasets"
        ).fetchall()
    return {
        r["source_type"]: {
            "rows_loaded": r["row_count"],
            "origin": r["origin"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    }


def delete_dataset(source_type: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM datasets WHERE source_type = ?", (source_type,))


# ------------------------------------------------------------ business cases

def create_business_case(
    title: str,
    description: str,
    estimated_cost: Optional[float],
    roi_plan: Dict[str, Any],
    generated_by: str,
    note: Optional[str],
    linked_opportunity: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    case_id = f"BC-{uuid.uuid4().hex[:8]}"
    submitted_at = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO business_cases (id, title, description, estimated_cost, submitted_at, "
            "roi_plan_json, generated_by, note, linked_opportunity_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id, title, description, estimated_cost, submitted_at,
                json.dumps(roi_plan), generated_by, note,
                json.dumps(linked_opportunity) if linked_opportunity else None,
            ),
        )
    return get_business_case(case_id)  # type: ignore[return-value]


def _case_from_row(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    readings = [
        dict(r) for r in conn.execute(
            "SELECT id, kpi_name, reading_date, value, note FROM kpi_readings "
            "WHERE case_id = ? ORDER BY reading_date", (row["id"],)
        ).fetchall()
    ]
    savings = [
        dict(r) for r in conn.execute(
            "SELECT id, entry_date, amount, note FROM savings_entries "
            "WHERE case_id = ? ORDER BY entry_date", (row["id"],)
        ).fetchall()
    ]
    case: Dict[str, Any] = {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "estimated_cost": row["estimated_cost"],
        "submitted_at": row["submitted_at"],
        "roi_plan": json.loads(row["roi_plan_json"]),
        "generated_by": row["generated_by"],
        "note": row["note"],
        "linked_opportunity": json.loads(row["linked_opportunity_json"])
        if row["linked_opportunity_json"] else None,
        "status": row["status"],
        "go_live_date": row["go_live_date"],
        "kpi_readings": readings,
        "savings_entries": savings,
    }
    case["tracking"] = _tracking_metrics(case)
    return case


def _tracking_metrics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if case["status"] != "implemented":
        return None
    total = sum(e["amount"] for e in case["savings_entries"])
    cost = case["estimated_cost"]
    roi_pct = None
    payback_progress_pct = None
    if cost and cost > 0:
        roi_pct = round((total - cost) / cost * 100, 1)
        payback_progress_pct = round(min(total / cost * 100, 100.0), 1)
    months_live = None
    if case["go_live_date"]:
        try:
            go_live = datetime.date.fromisoformat(case["go_live_date"])
            today = datetime.date.today()
            months_live = max(
                (today.year - go_live.year) * 12 + (today.month - go_live.month), 0
            )
        except ValueError:
            pass
    return {
        "total_realized_savings": round(total, 2),
        "realized_roi_pct": roi_pct,
        "payback_progress_pct": payback_progress_pct,
        "months_live": months_live,
        "readings_count": len(case["kpi_readings"]),
    }


def get_business_case(case_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM business_cases WHERE id = ?", (case_id,)
        ).fetchone()
        return _case_from_row(conn, row) if row else None


def list_business_cases() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM business_cases ORDER BY submitted_at DESC"
        ).fetchall()
        return [_case_from_row(conn, r) for r in rows]


def mark_implemented(case_id: str, go_live_date: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE business_cases SET status = 'implemented', go_live_date = ? WHERE id = ?",
            (go_live_date, case_id),
        )
        if cur.rowcount == 0:
            return None
    return get_business_case(case_id)


def add_kpi_reading(
    case_id: str, kpi_name: str, reading_date: str, value: float, note: Optional[str]
) -> Optional[Dict[str, Any]]:
    if get_business_case(case_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO kpi_readings (case_id, kpi_name, reading_date, value, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (case_id, kpi_name, reading_date, value, note),
        )
    return get_business_case(case_id)


def add_savings_entry(
    case_id: str, entry_date: str, amount: float, note: Optional[str]
) -> Optional[Dict[str, Any]]:
    if get_business_case(case_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO savings_entries (case_id, entry_date, amount, note) VALUES (?, ?, ?, ?)",
            (case_id, entry_date, amount, note),
        )
    return get_business_case(case_id)
