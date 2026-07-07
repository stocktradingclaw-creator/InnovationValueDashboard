"""McKinsey-style maturity assessment: framework -> waves -> calibration ->
benchmark -> gaps & value at stake -> roadmap -> readout."""
import json
from typing import Any, Dict, List, Optional

from . import db

LEVELS = ["Nascent", "Emerging", "Established", "Advanced", "Leading"]
WEIGHTS = {"critical": 1.5, "important": 1.0, "supporting": 0.6}
ROOT_CAUSES = ["capabilities", "process", "technology", "incentives", "mindsets & behaviors"]
VALUE_TYPES = ["revenue growth", "cost reduction", "speed to market", "risk mitigation"]
HORIZONS = ["0-3m", "3-9m", "9-18m"]

_DEFAULT_DIMS = [
    ("strategy", "Innovation strategy & ambition"),
    ("portfolio", "Portfolio & resource allocation"),
    ("insight", "Insight & ideation"),
    ("velocity", "Experimentation & development velocity"),
    ("scaling", "Commercialization & scaling"),
    ("talent", "Capabilities & talent"),
    ("culture", "Culture & incentives"),
    ("governance", "Governance & metrics"),
]


def _rubric(name: str) -> Dict[str, str]:
    frames = ["ad hoc and undocumented", "pockets of practice, person-dependent",
              "standardized and consistently applied", "measured and continuously improved",
              "a source of competitive advantage others benchmark"]
    return {str(i + 1): f"{LEVELS[i]}: {name} is {frames[i]}." for i in range(5)}


def get_framework() -> Dict[str, Any]:
    raw = db.meta_get("maturity_framework")
    if raw:
        return json.loads(raw)
    fw = {"name": "Innovation maturity", "dimensions": [
        {"key": k, "name": n, "description": f"How mature is {n.lower()}?",
         "target": 4 if i < 4 else 3, "weight": "critical" if i in (0, 3) else
         "important" if i < 6 else "supporting", "rubric": _rubric(n)}
        for i, (k, n) in enumerate(_DEFAULT_DIMS)]}
    db.meta_set("maturity_framework", json.dumps(fw))
    return fw


def save_framework(fw: Dict[str, Any]) -> Dict[str, Any]:
    for d in fw.get("dimensions", []):
        if not (1 <= int(d.get("target", 3)) <= 5):
            raise ValueError("targets must be 1-5")
        if d.get("weight") not in WEIGHTS:
            raise ValueError(f"weight must be one of {list(WEIGHTS)}")
    db.meta_set("maturity_framework", json.dumps(fw))
    return fw


def _benchmarks() -> Dict[str, Dict[str, float]]:
    raw = db.meta_get("maturity_benchmarks")
    if raw:
        return json.loads(raw)
    dims = [d["key"] for d in get_framework()["dimensions"]]
    b = {"industry median (editable placeholder)": {k: 2.6 for k in dims},
         "top quartile (editable placeholder)": {k: 3.8 for k in dims}}
    db.meta_set("maturity_benchmarks", json.dumps(b))
    return b


def save_benchmarks(b: Dict[str, Dict[str, float]]) -> Dict[str, Any]:
    db.meta_set("maturity_benchmarks", json.dumps(b))
    return b


def _tbl(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS maturity_waves (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS maturity_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, wave_id INTEGER NOT NULL,
        respondent TEXT NOT NULL, dimension TEXT NOT NULL, score INTEGER NOT NULL,
        confidence TEXT, evidence TEXT);
    CREATE TABLE IF NOT EXISTS maturity_calibrations (
        wave_id INTEGER NOT NULL, dimension TEXT NOT NULL, score REAL NOT NULL,
        note TEXT, PRIMARY KEY (wave_id, dimension));
    CREATE TABLE IF NOT EXISTS maturity_gaps (
        wave_id INTEGER NOT NULL, dimension TEXT NOT NULL, root_causes TEXT,
        value_type TEXT, low REAL, high REAL, confidence TEXT, effort TEXT,
        PRIMARY KEY (wave_id, dimension));
    CREATE TABLE IF NOT EXISTS maturity_initiatives (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, owner TEXT,
        dimensions TEXT, uplift REAL, horizon TEXT, status TEXT DEFAULT 'planned',
        milestones TEXT, created_at TEXT NOT NULL);
    """)


def create_wave(name: str) -> Dict[str, Any]:
    with db._conn() as conn:
        _tbl(conn)
        cur = conn.execute("INSERT INTO maturity_waves (name, created_at) VALUES (?, ?)",
                           (name, db._now()))
        return {"id": cur.lastrowid, "name": name}


def waves() -> List[Dict[str, Any]]:
    with db._conn() as conn:
        _tbl(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM maturity_waves ORDER BY id")]


def add_responses(wave_id: int, rows: List[Dict[str, Any]]) -> int:
    with db._conn() as conn:
        _tbl(conn)
        for r in rows:
            if not (1 <= int(r["score"]) <= 5):
                raise ValueError("scores must be 1-5")
            conn.execute(
                "INSERT INTO maturity_responses (wave_id, respondent, dimension, score, "
                "confidence, evidence) VALUES (?, ?, ?, ?, ?, ?)",
                (wave_id, r["respondent"], r["dimension"], int(r["score"]),
                 r.get("confidence"), r.get("evidence")))
    return len(rows)


def calibrate(wave_id: int, dimension: str, score: float, note: Optional[str]) -> None:
    with db._conn() as conn:
        _tbl(conn)
        conn.execute("INSERT INTO maturity_calibrations (wave_id, dimension, score, note) "
                     "VALUES (?, ?, ?, ?) ON CONFLICT (wave_id, dimension) DO UPDATE SET "
                     "score = excluded.score, note = excluded.note",
                     (wave_id, dimension, score, note))


def set_gap_value(wave_id: int, dimension: str, body: Dict[str, Any]) -> None:
    with db._conn() as conn:
        _tbl(conn)
        conn.execute(
            "INSERT INTO maturity_gaps (wave_id, dimension, root_causes, value_type, low, "
            "high, confidence, effort) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (wave_id, dimension) DO UPDATE SET root_causes=excluded.root_causes, "
            "value_type=excluded.value_type, low=excluded.low, high=excluded.high, "
            "confidence=excluded.confidence, effort=excluded.effort",
            (wave_id, dimension, json.dumps(body.get("root_causes") or []),
             body.get("value_type"), body.get("low"), body.get("high"),
             body.get("confidence"), body.get("effort")))


def add_initiative(body: Dict[str, Any]) -> Dict[str, Any]:
    with db._conn() as conn:
        _tbl(conn)
        cur = conn.execute(
            "INSERT INTO maturity_initiatives (title, owner, dimensions, uplift, horizon, "
            "status, milestones, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (body["title"], body.get("owner"), json.dumps(body.get("dimensions") or []),
             body.get("uplift") or 1, body.get("horizon") or "0-3m",
             body.get("status") or "planned", json.dumps(body.get("milestones") or []),
             db._now()))
        return {"id": cur.lastrowid, **body}


def initiatives() -> List[Dict[str, Any]]:
    with db._conn() as conn:
        _tbl(conn)
        return [{**dict(r), "dimensions": json.loads(r["dimensions"] or "[]"),
                 "milestones": json.loads(r["milestones"] or "[]")}
                for r in conn.execute("SELECT * FROM maturity_initiatives ORDER BY id")]


def wave_summary(wave_id: int) -> Dict[str, Any]:
    fw = get_framework()
    bench = _benchmarks()
    with db._conn() as conn:
        _tbl(conn)
        resp = [dict(r) for r in conn.execute(
            "SELECT dimension, score, respondent, confidence, evidence FROM "
            "maturity_responses WHERE wave_id = ?", (wave_id,))]
        cal = {r["dimension"]: dict(r) for r in conn.execute(
            "SELECT * FROM maturity_calibrations WHERE wave_id = ?", (wave_id,))}
        gaps = {r["dimension"]: dict(r) for r in conn.execute(
            "SELECT * FROM maturity_gaps WHERE wave_id = ?", (wave_id,))}
    dims = []
    for d in fw["dimensions"]:
        mine = [r["score"] for r in resp if r["dimension"] == d["key"]]
        self_avg = round(sum(mine) / len(mine), 2) if mine else None
        c = cal.get(d["key"], {}).get("score")
        gap = round((d["target"] - c) * WEIGHTS[d["weight"]], 2) if c is not None else None
        g = gaps.get(d["key"], {})
        dims.append({**{k: d[k] for k in ("key", "name", "target", "weight")},
                     "respondents": len(mine), "self_avg": self_avg, "calibrated": c,
                     "optimism_flag": bool(self_avg and c is not None and self_avg - c >= 1),
                     "gap_weighted": gap,
                     "benchmarks": {name: vals.get(d["key"]) for name, vals in bench.items()},
                     "root_causes": json.loads(g.get("root_causes") or "[]"),
                     "value_type": g.get("value_type"), "value_low": g.get("low"),
                     "value_high": g.get("high"), "value_confidence": g.get("confidence"),
                     "effort": g.get("effort"),
                     "evidence": [r["evidence"] for r in resp
                                  if r["dimension"] == d["key"] and r["evidence"]][:3]})
    scored = [d for d in dims if d["calibrated"] is not None]
    overall = round(sum(d["calibrated"] for d in scored) / len(scored), 2) if scored else None
    return {"wave_id": wave_id, "dimensions": dims, "overall_calibrated": overall,
            "total_value_low": round(sum(d["value_low"] or 0 for d in dims), 2),
            "total_value_high": round(sum(d["value_high"] or 0 for d in dims), 2)}


def readout() -> Dict[str, Any]:
    ws = waves()
    if not ws:
        return {"waves": [], "note": "No assessment waves yet."}
    latest = wave_summary(ws[-1]["id"])
    trend = [{"wave": w["name"], "id": w["id"],
              "dimensions": {d["key"]: d["calibrated"]
                             for d in wave_summary(w["id"])["dimensions"]}}
             for w in ws]
    ranked = sorted([d for d in latest["dimensions"] if d["value_high"]],
                    key=lambda d: -(d["value_high"] or 0))
    inits = initiatives()
    return {"waves": ws, "latest": latest, "trend": trend,
            "top_gaps": ranked[:3],
            "roadmap": {h: [i for i in inits if i["horizon"] == h] for h in HORIZONS}}


def seed_demo() -> None:
    get_framework(); _benchmarks()
    if waves():
        return
    import random
    random.seed(7)
    people = ["maria", "jordan", "priya", "alex", "sam", "lee"]
    base = {"strategy": 2, "portfolio": 2, "insight": 3, "velocity": 2,
            "scaling": 2, "talent": 3, "culture": 2, "governance": 2}
    for wave_i, (name, lift) in enumerate([("Baseline (Q1)", 0), ("Wave 2 (Q3)", 1)]):
        w = create_wave(name)
        rows = []
        for p in people:
            for k, b in base.items():
                rows.append({"respondent": p, "dimension": k,
                             "score": max(1, min(5, b + lift + random.choice([0, 0, 1]))),
                             "confidence": random.choice(["high", "medium"]),
                             "evidence": f"{p}: observed {k} practices in own unit"})
        add_responses(w["id"], rows)
        for k, b in base.items():
            calibrate(w["id"], k, max(1, b + lift - (1 if k in ("culture", "strategy") else 0)),
                      "calibrated against evidence pack")
        if wave_i == 1:
            for k, vt, lo, hi, eff in [("velocity", "speed to market", 800000, 2000000, "medium"),
                                       ("strategy", "revenue growth", 1500000, 4000000, "high"),
                                       ("governance", "risk mitigation", 300000, 900000, "low"),
                                       ("culture", "cost reduction", 200000, 600000, "medium")]:
                set_gap_value(w["id"], k, {"root_causes": ["process", "incentives"],
                                           "value_type": vt, "low": lo, "high": hi,
                                           "confidence": "medium", "effort": eff})
    for t, h, dims_, up in [("Stand up innovation portfolio board", "0-3m", ["governance"], 1),
                            ("Experiment velocity sprint program", "0-3m", ["velocity"], 1),
                            ("Strategy & ambition alignment offsite", "3-9m", ["strategy"], 1),
                            ("Incentive redesign for intelligent failure", "9-18m", ["culture"], 2)]:
        add_initiative({"title": t, "horizon": h, "dimensions": dims_, "uplift": up,
                        "owner": "maria", "milestones": [{"name": "kickoff", "done": True}]})
