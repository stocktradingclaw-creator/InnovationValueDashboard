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
CREATE TABLE IF NOT EXISTS metric_bindings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id             TEXT NOT NULL REFERENCES business_cases(id),
    kpi_name            TEXT,
    label               TEXT NOT NULL,
    definition_json     TEXT NOT NULL,
    unit                TEXT NOT NULL,
    baseline_value      REAL NOT NULL,
    baseline_rows       INTEGER NOT NULL,
    baseline_captured_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    binding_id   INTEGER NOT NULL REFERENCES metric_bindings(id),
    observed_at  TEXT NOT NULL,
    value        REAL NOT NULL,
    rows_matched INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ideas (
    id                      TEXT PRIMARY KEY,
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    submitter               TEXT,
    submitted_at            TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'triaged',
    assessment_json         TEXT,
    promoted_case_id        TEXT,
    category                TEXT,
    estimated_annual_benefit REAL,
    source                  TEXT NOT NULL DEFAULT 'manual'
);
CREATE TABLE IF NOT EXISTS workflow_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    action       TEXT NOT NULL,
    actor        TEXT,
    comment      TEXT
);
CREATE TABLE IF NOT EXISTS automation_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at  TEXT NOT NULL,
    rule    TEXT NOT NULL,
    action  TEXT NOT NULL,
    subject TEXT,
    detail  TEXT
);
CREATE TABLE IF NOT EXISTS stage_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id    TEXT NOT NULL REFERENCES business_cases(id),
    stage      TEXT NOT NULL,
    entered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    name          TEXT PRIMARY KEY,
    role          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    password_hash TEXT
);
CREATE TABLE IF NOT EXISTS studio_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    topic      TEXT NOT NULL,
    horizon    TEXT,
    output     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metric_snapshots (
    day      TEXT PRIMARY KEY,
    verified REAL NOT NULL,
    claimed  REAL NOT NULL,
    ideas    INTEGER NOT NULL,
    cases    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_citations (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id  TEXT NOT NULL,
    case_id  TEXT NOT NULL,
    cited_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attachments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    filename     TEXT NOT NULL,
    content_type TEXT,
    size         INTEGER NOT NULL,
    uploaded_by  TEXT,
    uploaded_at  TEXT NOT NULL,
    data         BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id    TEXT NOT NULL,
    reviewer   TEXT NOT NULL,
    scores     TEXT NOT NULL,
    comment    TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (idea_id, reviewer)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    actor   TEXT,
    action  TEXT NOT NULL,
    subject TEXT,
    detail  TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_name  TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id          TEXT NOT NULL REFERENCES business_cases(id),
    hypothesis       TEXT NOT NULL,
    method           TEXT NOT NULL,
    success_criteria TEXT NOT NULL,
    cost             REAL,
    started_at       TEXT NOT NULL,
    concluded_at     TEXT,
    outcome          TEXT,
    learnings        TEXT
);
CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient    TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    message      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    question   TEXT NOT NULL,
    theme      TEXT,
    status     TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    closes_at  TEXT
);
CREATE TABLE IF NOT EXISTS strategic_initiatives (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    objective  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    rank       INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS idea_comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id    TEXT NOT NULL REFERENCES ideas(id),
    author     TEXT NOT NULL,
    comment    TEXT NOT NULL,
    build_on   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_votes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id    TEXT NOT NULL REFERENCES ideas(id),
    voter      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (idea_id, voter)
);
CREATE TABLE IF NOT EXISTS funding_tranches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     TEXT NOT NULL REFERENCES business_cases(id),
    label       TEXT NOT NULL,
    amount      REAL NOT NULL,
    milestone   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'planned',
    released_at TEXT,
    released_by TEXT
);
"""

# Innovation lifecycle stages, in order. `status` (proposed/implemented) is kept
# for tracking math; `stage` is the richer pipeline position.
STAGES = ["draft", "proposed", "experiment", "approved", "in_delivery", "live", "value_realized", "scale", "closed"]


def _db_path() -> str:
    return os.environ.get(
        "IVD_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "data.db"),
    )


def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(business_cases)")}
    if "stage" not in cols:
        conn.execute(
            "ALTER TABLE business_cases ADD COLUMN stage TEXT NOT NULL DEFAULT 'proposed'"
        )
        conn.execute("UPDATE business_cases SET stage = 'live' WHERE status = 'implemented'")
    if "horizon" not in cols:
        conn.execute("ALTER TABLE business_cases ADD COLUMN horizon TEXT NOT NULL DEFAULT 'h1'")
    idea_cols = {r[1] for r in conn.execute("PRAGMA table_info(ideas)")}
    if idea_cols and "category" not in idea_cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN category TEXT")
        conn.execute("ALTER TABLE ideas ADD COLUMN estimated_annual_benefit REAL")
        conn.execute("ALTER TABLE ideas ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
    if idea_cols and "benefit_type" not in idea_cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN benefit_type TEXT")
        conn.execute("ALTER TABLE ideas ADD COLUMN horizon TEXT")
        conn.execute("ALTER TABLE ideas ADD COLUMN challenge_id TEXT")
    if idea_cols and "beneficiary" not in idea_cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN beneficiary TEXT")
        conn.execute("ALTER TABLE ideas ADD COLUMN pain_point TEXT")
    if idea_cols and "initiative_id" not in idea_cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN initiative_id TEXT")
        idea_cols.add("initiative_id")
    if idea_cols and "initiative_ids" not in idea_cols:
        conn.execute("ALTER TABLE ideas ADD COLUMN initiative_ids TEXT")
        conn.execute(
            "UPDATE ideas SET initiative_ids = '[\"' || initiative_id || '\"]' "
            "WHERE initiative_id IS NOT NULL")
    user_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    if user_cols and "password_hash" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    si_cols = {r[1] for r in conn.execute("PRAGMA table_info(strategic_initiatives)")}
    if si_cols and "rank" not in si_cols:
        conn.execute("ALTER TABLE strategic_initiatives ADD COLUMN rank INTEGER NOT NULL DEFAULT 0")
    if idea_cols:
        # stage-gate lifecycle: legacy statuses map onto the gated pipeline
        conn.execute("UPDATE ideas SET status = 'proposed' WHERE status = 'triaged'")
        conn.execute("UPDATE ideas SET status = 'business_case' WHERE status = 'promoted'")
    if "initiative_id" not in cols:
        conn.execute("ALTER TABLE business_cases ADD COLUMN initiative_id TEXT")
    if cols and "red_team_json" not in cols:
        conn.execute("ALTER TABLE business_cases ADD COLUMN red_team_json TEXT")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
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
    stage: str = "proposed",
    horizon: str = "h1",
    initiative_id: Optional[str] = None,
) -> Dict[str, Any]:
    case_id = f"BC-{uuid.uuid4().hex[:8]}"
    submitted_at = _now()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO business_cases (id, title, description, estimated_cost, submitted_at, "
            "roi_plan_json, generated_by, note, linked_opportunity_json, stage, horizon, "
            "initiative_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                case_id, title, description, estimated_cost, submitted_at,
                json.dumps(roi_plan), generated_by, note,
                json.dumps(linked_opportunity) if linked_opportunity else None,
                stage, horizon, initiative_id,
            ),
        )
        conn.execute(
            "INSERT INTO stage_history (case_id, stage, entered_at) VALUES (?, ?, ?)",
            (case_id, stage, submitted_at),
        )
    return get_business_case(case_id)  # type: ignore[return-value]


def set_stage(case_id: str, stage: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE business_cases SET stage = ? WHERE id = ?", (stage, case_id)
        )
        if cur.rowcount == 0:
            return None
        conn.execute(
            "INSERT INTO stage_history (case_id, stage, entered_at) VALUES (?, ?, ?)",
            (case_id, stage, _now()),
        )
    return get_business_case(case_id)


def _binding_payload(conn: sqlite3.Connection, b: sqlite3.Row) -> Dict[str, Any]:
    from . import metrics  # local import: metrics has no db dependency

    observations = [
        dict(o) for o in conn.execute(
            "SELECT id, observed_at, value, rows_matched FROM metric_observations "
            "WHERE binding_id = ? ORDER BY observed_at", (b["id"],)
        ).fetchall()
    ]
    definition = json.loads(b["definition_json"])
    latest = observations[-1]["value"] if observations else None
    payload = {
        "id": b["id"],
        "kpi_name": b["kpi_name"],
        "label": b["label"],
        "definition": definition,
        "unit": b["unit"],
        "baseline_value": b["baseline_value"],
        "baseline_rows": b["baseline_rows"],
        "baseline_captured_at": b["baseline_captured_at"],
        "observations": observations,
        "latest_value": latest,
        "delta": round(b["baseline_value"] - latest, 2) if latest is not None else None,
        "annualized_delta": (
            metrics.annualized_delta(definition, b["baseline_value"], latest)
            if latest is not None else None
        ),
    }
    return payload


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
    bindings = [
        _binding_payload(conn, b) for b in conn.execute(
            "SELECT * FROM metric_bindings WHERE case_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
    ]
    experiments = [
        dict(r) for r in conn.execute(
            "SELECT id, hypothesis, method, success_criteria, cost, started_at, "
            "concluded_at, outcome, learnings FROM experiments WHERE case_id = ? ORDER BY id",
            (row["id"],),
        ).fetchall()
    ]
    tranches = [
        dict(r) for r in conn.execute(
            "SELECT id, label, amount, milestone, status, released_at, released_by "
            "FROM funding_tranches WHERE case_id = ? ORDER BY id", (row["id"],),
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
        "stage": row["stage"],
        "horizon": row["horizon"],
        "initiative_id": row["initiative_id"],
        "red_team": json.loads(row["red_team_json"]) if row["red_team_json"] else None,
        "go_live_date": row["go_live_date"],
        "experiments": experiments,
        "funding": {
            "planned": round(sum(t["amount"] for t in tranches), 2),
            "released": round(sum(t["amount"] for t in tranches if t["status"] == "released"), 2),
            "tranches": tranches,
        },
        "kpi_readings": readings,
        "savings_entries": savings,
        "metric_bindings": bindings,
        "stage_history": [
            dict(r) for r in conn.execute(
                "SELECT stage, entered_at FROM stage_history WHERE case_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
        ],
    }
    case["tracking"] = _tracking_metrics(case)
    return case


def _tracking_metrics(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if case["status"] != "implemented":
        return None
    total = sum(e["amount"] for e in case["savings_entries"])
    # measured (hard) value: annualizable reductions computed from data,
    # kept strictly separate from self-reported (claimed) savings entries
    measured_annual = sum(
        b["annualized_delta"] for b in case["metric_bindings"]
        if b["annualized_delta"] is not None
    )
    # metered funding: once tranches are released, they are the cost basis
    released = case["funding"]["released"]
    cost = released if released > 0 else case["estimated_cost"]
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
        "measured_annual_savings": round(measured_annual, 2),
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
            "UPDATE business_cases SET status = 'implemented', go_live_date = ?, "
            "stage = 'live' WHERE id = ?",
            (go_live_date, case_id),
        )
        if cur.rowcount == 0:
            return None
        conn.execute(
            "INSERT INTO stage_history (case_id, stage, entered_at) VALUES (?, ?, ?)",
            (case_id, "live", _now()),
        )
    return get_business_case(case_id)


# ------------------------------------------------------------------------ ideas

def create_idea(
    title: str,
    description: str,
    submitter: Optional[str],
    assessment: Optional[Dict[str, Any]],
    category: Optional[str] = None,
    estimated_annual_benefit: Optional[float] = None,
    source: str = "manual",
    submitted_at: Optional[str] = None,
    benefit_type: Optional[str] = None,
    horizon: Optional[str] = None,
    challenge_id: Optional[str] = None,
    beneficiary: Optional[str] = None,
    pain_point: Optional[str] = None,
    initiative_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    idea_id = f"IDEA-{uuid.uuid4().hex[:8]}"
    ids = initiative_ids or []
    with _conn() as conn:
        conn.execute(
            "INSERT INTO ideas (id, title, description, submitter, submitted_at, status, "
            "assessment_json, category, estimated_annual_benefit, source, benefit_type, "
            "horizon, challenge_id, beneficiary, pain_point, initiative_id, initiative_ids) "
            "VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (idea_id, title, description, submitter, submitted_at or _now(),
             json.dumps(assessment) if assessment else None,
             category, estimated_annual_benefit, source, benefit_type, horizon, challenge_id,
             beneficiary, pain_point, ids[0] if ids else None,
             json.dumps(ids) if ids else None),
        )
    return get_idea(idea_id)  # type: ignore[return-value]


def _idea_social(idea_id: str) -> Dict[str, Any]:
    with _conn() as conn:
        comments = [
            dict(r) for r in conn.execute(
                "SELECT id, author, comment, build_on, created_at FROM idea_comments "
                "WHERE idea_id = ? ORDER BY id", (idea_id,),
            ).fetchall()
        ]
        voters = [
            r["voter"] for r in conn.execute(
                "SELECT voter FROM idea_votes WHERE idea_id = ? ORDER BY id", (idea_id,),
            ).fetchall()
        ]
    return {"comments": comments, "voters": voters, "vote_count": len(voters)}


def _idea_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "submitter": row["submitter"],
        "submitted_at": row["submitted_at"],
        "status": row["status"],
        "assessment": json.loads(row["assessment_json"]) if row["assessment_json"] else None,
        "promoted_case_id": row["promoted_case_id"],
        "category": row["category"],
        "estimated_annual_benefit": row["estimated_annual_benefit"],
        "source": row["source"],
        "benefit_type": row["benefit_type"],
        "horizon": row["horizon"],
        "challenge_id": row["challenge_id"],
        "beneficiary": row["beneficiary"],
        "pain_point": row["pain_point"],
        "initiative_id": row["initiative_id"],
        "initiative_ids": (json.loads(row["initiative_ids"]) if row["initiative_ids"]
                           else ([row["initiative_id"]] if row["initiative_id"] else [])),
        **_idea_social(row["id"]),
    }


def update_idea_assessment(idea_id: str, assessment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE ideas SET assessment_json = ? WHERE id = ?",
            (json.dumps(assessment), idea_id),
        )
        if cur.rowcount == 0:
            return None
    return get_idea(idea_id)


def add_workflow_event(subject_type: str, subject_id: str, action: str,
                       actor: Optional[str], comment: Optional[str]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO workflow_events (created_at, subject_type, subject_id, action, "
            "actor, comment) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), subject_type, subject_id, action, actor, comment),
        )


def workflow_events(limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT created_at, subject_type, subject_id, action, actor, comment "
            "FROM workflow_events ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_idea(idea_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM ideas WHERE id = ?", (idea_id,)).fetchone()
    return _idea_from_row(row) if row else None


def list_ideas() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM ideas ORDER BY submitted_at DESC").fetchall()
    return [_idea_from_row(r) for r in rows]


def update_idea(idea_id: str, status: str,
                promoted_case_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE ideas SET status = ?, promoted_case_id = COALESCE(?, promoted_case_id) "
            "WHERE id = ?",
            (status, promoted_case_id, idea_id),
        )
        if cur.rowcount == 0:
            return None
    return get_idea(idea_id)


# -------------------------------------------------------------- automation log

def log_automation(rule: str, action: str, subject: Optional[str], detail: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO automation_log (run_at, rule, action, subject, detail) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), rule, action, subject, detail),
        )


def automation_log_entries(limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT run_at, rule, action, subject, detail FROM automation_log "
            "ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def meta_get(key: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


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


def create_metric_binding(
    case_id: str,
    label: str,
    kpi_name: Optional[str],
    definition: Dict[str, Any],
    unit: str,
    baseline_value: float,
    baseline_rows: int,
) -> Optional[Dict[str, Any]]:
    if get_business_case(case_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO metric_bindings (case_id, kpi_name, label, definition_json, unit, "
            "baseline_value, baseline_rows, baseline_captured_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, kpi_name, label, json.dumps(definition), unit,
             baseline_value, baseline_rows, _now()),
        )
    return get_business_case(case_id)


def get_binding(case_id: str, binding_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM metric_bindings WHERE id = ? AND case_id = ?",
            (binding_id, case_id),
        ).fetchone()
        return _binding_payload(conn, row) if row else None


def add_metric_observation(
    case_id: str, binding_id: int, value: float, rows_matched: int
) -> Optional[Dict[str, Any]]:
    if get_binding(case_id, binding_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO metric_observations (binding_id, observed_at, value, rows_matched) "
            "VALUES (?, ?, ?, ?)",
            (binding_id, _now(), value, rows_matched),
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


# ---------------------------------------------------------------- experiments

def add_experiment(case_id: str, hypothesis: str, method: str,
                   success_criteria: str, cost: Optional[float]) -> Optional[Dict[str, Any]]:
    if get_business_case(case_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO experiments (case_id, hypothesis, method, success_criteria, cost, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?)",
            (case_id, hypothesis, method, success_criteria, cost, _now()),
        )
    return get_business_case(case_id)


def conclude_experiment(case_id: str, experiment_id: int, outcome: str,
                        learnings: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE experiments SET concluded_at = ?, outcome = ?, learnings = ? "
            "WHERE id = ? AND case_id = ? AND concluded_at IS NULL",
            (_now(), outcome, learnings, experiment_id, case_id),
        )
        if cur.rowcount == 0:
            return None
    return get_business_case(case_id)


def experiment_stats() -> Dict[str, Any]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT outcome, COUNT(*) AS n FROM experiments "
            "WHERE concluded_at IS NOT NULL GROUP BY outcome"
        ).fetchall()
        running = conn.execute(
            "SELECT COUNT(*) AS n FROM experiments WHERE concluded_at IS NULL"
        ).fetchone()["n"]
    by_outcome = {r["outcome"]: r["n"] for r in rows}
    concluded = sum(by_outcome.values())
    decisive = by_outcome.get("kill", 0) + by_outcome.get("proceed", 0)
    return {
        "running": running,
        "concluded": concluded,
        "by_outcome": by_outcome,
        "kill_rate": round(by_outcome.get("kill", 0) / decisive, 2) if decisive else None,
    }


# -------------------------------------------------------------- notifications

def notify(recipient: Optional[str], subject_type: str, subject_id: str, message: str) -> None:
    if not recipient:
        return
    with _conn() as conn:
        conn.execute(
            "INSERT INTO notifications (recipient, subject_type, subject_id, message, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (recipient.strip(), subject_type, subject_id, message, _now()),
        )
    url = meta_get("notify_webhook")
    if url:
        try:
            import json as _json
            import urllib.request
            req = urllib.request.Request(
                url, data=_json.dumps({"text": f"[Innovation Hub] {message}"}).encode(),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2)
        except Exception:
            pass  # notifications must never break the workflow



def notifications_for(recipient: str, limit: int = 50) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, subject_type, subject_id, message, created_at FROM notifications "
            "WHERE lower(recipient) = lower(?) ORDER BY id DESC LIMIT ?",
            (recipient.strip(), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def submitter_for_case(case_id: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT submitter FROM ideas WHERE promoted_case_id = ?", (case_id,)
        ).fetchone()
    return row["submitter"] if row else None


# ----------------------------------------------------------------- challenges

def create_challenge(title: str, question: str, theme: Optional[str],
                     closes_at: Optional[str]) -> Dict[str, Any]:
    challenge_id = f"CH-{uuid.uuid4().hex[:8]}"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO challenges (id, title, question, theme, created_at, closes_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (challenge_id, title, question, theme, _now(), closes_at),
        )
    return get_challenge(challenge_id)  # type: ignore[return-value]


def get_challenge(challenge_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,)).fetchone()
        if row is None:
            return None
        ideas_count = conn.execute(
            "SELECT COUNT(*) AS n FROM ideas WHERE challenge_id = ?", (challenge_id,)
        ).fetchone()["n"]
    challenge = dict(row)
    challenge["ideas_count"] = ideas_count
    return challenge


def list_challenges() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute("SELECT id FROM challenges ORDER BY created_at DESC").fetchall()
    return [get_challenge(r["id"]) for r in rows]  # type: ignore[misc]


def close_challenge(challenge_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE challenges SET status = 'closed' WHERE id = ?", (challenge_id,)
        )
        if cur.rowcount == 0:
            return None
    return get_challenge(challenge_id)


# ------------------------------------------------------------ funding tranches

def add_tranche(case_id: str, label: str, amount: float,
                milestone: str) -> Optional[Dict[str, Any]]:
    if get_business_case(case_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO funding_tranches (case_id, label, amount, milestone) "
            "VALUES (?, ?, ?, ?)",
            (case_id, label, amount, milestone),
        )
    return get_business_case(case_id)


def release_tranche(case_id: str, tranche_id: int,
                    released_by: Optional[str]) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE funding_tranches SET status = 'released', released_at = ?, "
            "released_by = ? WHERE id = ? AND case_id = ? AND status = 'planned'",
            (_now(), released_by, tranche_id, case_id),
        )
        if cur.rowcount == 0:
            return None
    return get_business_case(case_id)


# ------------------------------------------------------------- social ideation

def add_comment(idea_id: str, author: str, comment: str,
                build_on: bool) -> Optional[Dict[str, Any]]:
    if get_idea(idea_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT INTO idea_comments (idea_id, author, comment, build_on, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (idea_id, author, comment, 1 if build_on else 0, _now()),
        )
    return get_idea(idea_id)


def add_vote(idea_id: str, voter: str) -> Optional[Dict[str, Any]]:
    """Idempotent: voting twice is a no-op. Votes are signal, never decision."""
    if get_idea(idea_id) is None:
        return None
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO idea_votes (idea_id, voter, created_at) VALUES (?, ?, ?)",
            (idea_id, voter.strip(), _now()),
        )
    return get_idea(idea_id)


def learnings(limit: int = 50) -> List[Dict[str, Any]]:
    """The learning library: every concluded experiment's lesson, newest first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT e.outcome, e.learnings, e.concluded_at, e.hypothesis, "
            "b.id AS case_id, b.title AS case_title "
            "FROM experiments e JOIN business_cases b ON b.id = e.case_id "
            "WHERE e.concluded_at IS NOT NULL ORDER BY e.concluded_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------- strategic initiatives

def create_initiative(name: str, objective: str) -> Dict[str, Any]:
    initiative_id = f"SI-{uuid.uuid4().hex[:8]}"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO strategic_initiatives (id, name, objective, created_at) "
            "VALUES (?, ?, ?, ?)",
            (initiative_id, name, objective, _now()),
        )
    return get_initiative(initiative_id)  # type: ignore[return-value]


def get_initiative(initiative_id: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM strategic_initiatives WHERE id = ?", (initiative_id,)
        ).fetchone()
    return dict(row) if row else None


def list_initiatives() -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM strategic_initiatives ORDER BY rank, created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def idea_transitions() -> List[Dict[str, Any]]:
    """Gate transitions for ideas (qualify/prioritize/develop) for dwell math."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT subject_id, action, created_at FROM workflow_events "
            "WHERE subject_type = 'idea' AND action IN ('qualify', 'prioritize', 'develop') "
            "ORDER BY id",
        ).fetchall()
    return [dict(r) for r in rows]


def update_initiative(initiative_id: str, name: Optional[str],
                      objective: Optional[str]) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE strategic_initiatives SET name = COALESCE(?, name), "
            "objective = COALESCE(?, objective) WHERE id = ?",
            (name, objective, initiative_id),
        )
        if cur.rowcount == 0:
            return None
    return get_initiative(initiative_id)


def reorder_initiatives(ids: List[str]) -> None:
    with _conn() as conn:
        for rank, initiative_id in enumerate(ids):
            conn.execute(
                "UPDATE strategic_initiatives SET rank = ? WHERE id = ?",
                (rank, initiative_id),
            )


def update_challenge(challenge_id: str, title: Optional[str], question: Optional[str],
                     theme: Optional[str]) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE challenges SET title = COALESCE(?, title), "
            "question = COALESCE(?, question), theme = COALESCE(?, theme) WHERE id = ?",
            (title, question, theme, challenge_id),
        )
        if cur.rowcount == 0:
            return None
    return get_challenge(challenge_id)


def events_for(subject_type: str, subject_id: str) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT created_at, action, actor, comment FROM workflow_events "
            "WHERE subject_type = ? AND subject_id = ? ORDER BY id",
            (subject_type, subject_id),
        ).fetchall()
    return [dict(r) for r in rows]


def _hash_password(password: str, salt: Optional[str] = None) -> str:
    import hashlib
    import os as _os
    salt = salt or _os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"{salt}${digest.hex()}"


def replace_users(users: List[Dict[str, str]]) -> List[Dict[str, str]]:
    with _conn() as conn:
        old = {r["name"]: r["password_hash"]
               for r in conn.execute("SELECT name, password_hash FROM users")}
        conn.execute("DELETE FROM users")
        for u in users:
            name = u["name"].strip().lower()
            pw = (u.get("password") or "").strip()
            conn.execute(
                "INSERT INTO users (name, role, created_at, password_hash) VALUES (?, ?, ?, ?)",
                (name, u["role"], _now(),
                 _hash_password(pw) if pw else old.get(name)),
            )
        conn.execute(
            "DELETE FROM sessions WHERE user_name NOT IN (SELECT name FROM users)")
    return list_users()


def create_user(name: str, role: str, password: str) -> Dict[str, str]:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO users (name, role, created_at, password_hash) VALUES (?, ?, ?, ?)",
            (name.strip().lower(), role, _now(), _hash_password(password)),
        )
    return {"name": name.strip().lower(), "role": role}


def verify_login(name: str, password: str) -> Optional[Dict[str, str]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT name, role, password_hash FROM users WHERE name = ?",
            ((name or "").strip().lower(),),
        ).fetchone()
    if row is None or not row["password_hash"]:
        return None
    salt = row["password_hash"].split("$", 1)[0]
    if _hash_password(password, salt) != row["password_hash"]:
        return None
    return {"name": row["name"], "role": row["role"]}


def create_session(user_name: str) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_name, created_at) VALUES (?, ?, ?)",
            (token, user_name, _now()),
        )
    return token


def session_user(token: str) -> Optional[Dict[str, str]]:
    if not token:
        return None
    with _conn() as conn:
        row = conn.execute(
            "SELECT u.name, u.role FROM sessions s JOIN users u ON u.name = s.user_name "
            "WHERE s.token = ?", (token,),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def list_users() -> List[Dict[str, str]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT name, role, password_hash IS NOT NULL AS has_password "
            "FROM users ORDER BY name").fetchall()
    return [{"name": r["name"], "role": r["role"], "has_password": bool(r["has_password"])}
            for r in rows]


def get_role(name: str) -> Optional[str]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE name = ?", ((name or "").strip().lower(),)
        ).fetchone()
    return row["role"] if row else None


def audit(action: str, actor: Optional[str], subject: Optional[str] = None,
          detail: Optional[str] = None) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO audit_log (at, actor, action, subject, detail) VALUES (?, ?, ?, ?, ?)",
            (_now(), actor, action, subject, (detail or "")[:500]),
        )


def audit_entries(limit: int = 1000) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT at, actor, action, subject, detail FROM audit_log "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def dump_state() -> Dict[str, Any]:
    """Portable snapshot of every table — durability escape hatch for
    ephemeral hosting and tenant migration."""
    out: Dict[str, Any] = {"_format": 1}
    with _conn() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        for t in tables:
            out[t] = [dict(r) for r in conn.execute(f"SELECT * FROM {t}")]
    return out


def restore_state(state: Dict[str, Any]) -> Dict[str, int]:
    if state.get("_format") != 1:
        raise ValueError("unrecognized snapshot format")
    counts: Dict[str, int] = {}
    with _conn() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")}
        for t, rows in state.items():
            if t.startswith("_") or t not in tables or not isinstance(rows, list):
                continue
            conn.execute(f"DELETE FROM {t}")
            for row in rows:
                cols = list(row.keys())
                conn.execute(
                    f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                    [row[c] for c in cols])
            counts[t] = len(rows)
    return counts


def add_attachment(subject_type: str, subject_id: str, filename: str,
                   content_type: Optional[str], data: bytes,
                   uploaded_by: Optional[str]) -> Dict[str, Any]:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO attachments (subject_type, subject_id, filename, content_type, "
            "size, uploaded_by, uploaded_at, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (subject_type, subject_id, filename, content_type, len(data),
             uploaded_by, _now(), data))
        aid = cur.lastrowid
    return {"id": aid, "filename": filename, "content_type": content_type,
            "size": len(data), "uploaded_by": uploaded_by}


def list_attachments(subject_type: str, subject_id: str) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, filename, content_type, size, uploaded_by, uploaded_at "
            "FROM attachments WHERE subject_type = ? AND subject_id = ? ORDER BY id",
            (subject_type, subject_id)).fetchall()
    return [dict(r) for r in rows]


def get_attachment(attachment_id: int) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id = ?",
                           (attachment_id,)).fetchone()
    return dict(row) if row else None


def save_review(idea_id: str, reviewer: str, scores: Dict[str, int],
                comment: Optional[str]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO reviews (idea_id, reviewer, scores, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (idea_id, reviewer) DO UPDATE SET "
            "scores = excluded.scores, comment = excluded.comment, "
            "created_at = excluded.created_at",
            (idea_id, reviewer.strip().lower(), json.dumps(scores), comment, _now()))


def reviews_for(idea_id: str) -> List[Dict[str, Any]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT reviewer, scores, comment, created_at FROM reviews "
            "WHERE idea_id = ? ORDER BY created_at", (idea_id,)).fetchall()
    return [{**dict(r), "scores": json.loads(r["scores"])} for r in rows]


def review_summary(idea_id: str) -> Dict[str, Any]:
    revs = reviews_for(idea_id)
    if not revs:
        return {"count": 0, "average": None}
    means = [sum(r["scores"].values()) / max(len(r["scores"]), 1) for r in revs]
    return {"count": len(revs), "average": round(sum(means) / len(means), 1)}


def set_red_team(case_id: str, memo: Dict[str, Any]) -> None:
    with _conn() as conn:
        conn.execute("UPDATE business_cases SET red_team_json = ? WHERE id = ?",
                     (json.dumps(memo), case_id))


def cite_learning(idea_id: str, case_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO learning_citations (idea_id, case_id, cited_at) VALUES (?, ?, ?)",
            (idea_id, case_id, _now()))


def learning_dividends() -> List[Dict[str, Any]]:
    """Most-cited kills: learnings that keep paying."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT lc.case_id, b.title AS case_title, COUNT(*) AS citations "
            "FROM learning_citations lc JOIN business_cases b ON b.id = lc.case_id "
            "GROUP BY lc.case_id ORDER BY citations DESC LIMIT 20").fetchall()
    return [dict(r) for r in rows]


def record_snapshot(day: str, verified: float, claimed: float,
                    ideas: int, cases: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO metric_snapshots (day, verified, claimed, ideas, cases) "
            "VALUES (?, ?, ?, ?, ?)", (day, verified, claimed, ideas, cases))


def snapshot_before(day: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM metric_snapshots WHERE day < ? ORDER BY day DESC LIMIT 1",
            (day,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM metric_snapshots ORDER BY day ASC LIMIT 1").fetchone()
    return dict(row) if row else None


def update_idea_fields(idea_id: str, title: str, description: str,
                       benefit: Optional[float]) -> None:
    with _conn() as conn:
        if benefit is not None:
            conn.execute("UPDATE ideas SET title = ?, description = ?, "
                         "estimated_annual_benefit = ? WHERE id = ?",
                         (title, description, benefit, idea_id))
        else:
            conn.execute("UPDATE ideas SET title = ?, description = ? WHERE id = ?",
                         (title, description, idea_id))


def save_studio_run(kind: str, topic: str, horizon: Optional[str],
                    output: Dict[str, Any]) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO studio_runs (kind, topic, horizon, output, created_at) "
            "VALUES (?, ?, ?, ?, ?)", (kind, topic, horizon, json.dumps(output), _now()))


def latest_studio_run(kind: str) -> Optional[Dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT topic, horizon, output, created_at FROM studio_runs "
            "WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)).fetchone()
    if row is None:
        return None
    return {"topic": row["topic"], "horizon": row["horizon"],
            "created_at": row["created_at"], **json.loads(row["output"])}
