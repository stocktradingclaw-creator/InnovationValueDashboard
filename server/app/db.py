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
    created_at TEXT NOT NULL
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
    if "initiative_id" not in cols:
        conn.execute("ALTER TABLE business_cases ADD COLUMN initiative_id TEXT")


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
    initiative_id: Optional[str] = None,
) -> Dict[str, Any]:
    idea_id = f"IDEA-{uuid.uuid4().hex[:8]}"
    with _conn() as conn:
        conn.execute(
            "INSERT INTO ideas (id, title, description, submitter, submitted_at, status, "
            "assessment_json, category, estimated_annual_benefit, source, benefit_type, "
            "horizon, challenge_id, beneficiary, pain_point, initiative_id) "
            "VALUES (?, ?, ?, ?, ?, 'triaged', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (idea_id, title, description, submitter, submitted_at or _now(),
             json.dumps(assessment) if assessment else None,
             category, estimated_annual_benefit, source, benefit_type, horizon, challenge_id,
             beneficiary, pain_point, initiative_id),
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
            "SELECT * FROM strategic_initiatives ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]
