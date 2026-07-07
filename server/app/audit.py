"""Innovation Management Audit engine: campaigns, curated responses, scoring,
perception gaps, suppression, recommendations, value index, quadrant."""
import json
from itertools import combinations
from typing import Any, Dict, List, Optional

from . import db
from . import audit_seed as seed

IMPACT = {"H": 3, "M": 2, "L": 1}
EFFORT = {"S": 1, "M": 2, "L": 3}
LEVELS = ["executive", "management", "practitioner"]


def _tbl(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS audit_campaigns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, status TEXT DEFAULT 'open',
        is_anonymous INTEGER DEFAULT 0, config TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL, person TEXT,
        level TEXT NOT NULL, org_unit TEXT, status TEXT DEFAULT 'invited');
    CREATE TABLE IF NOT EXISTS audit_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL,
        level TEXT NOT NULL, org_unit TEXT, respondent TEXT, submitted_at TEXT NOT NULL,
        items TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_roadmap (
        id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id INTEGER NOT NULL,
        template_id TEXT, dimension TEXT, title TEXT NOT NULL, description TEXT,
        horizon TEXT, status TEXT DEFAULT 'generated', priority REAL,
        owner TEXT, due_date TEXT, kpi TEXT);
    CREATE TABLE IF NOT EXISTS value_index_snapshots (
        period TEXT PRIMARY KEY, value REAL NOT NULL, source TEXT NOT NULL);
    """)


def config(campaign: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = {"readiness": seed.READINESS_THRESHOLD, "gap_threshold": seed.PERCEPTION_GAP_THRESHOLD,
            "min_segment_n": seed.MIN_SEGMENT_N, "value_threshold": seed.VALUE_QUADRANT_THRESHOLD,
            "weights": dict(seed.WEIGHTS), "bands": seed.BANDS}
    if campaign and campaign.get("config"):
        base.update(json.loads(campaign["config"]))
    return base


def band(score: float, cfg: Dict[str, Any]) -> str:
    for lo, hi, name in cfg["bands"]:
        if lo <= score <= hi:
            return name
    return "Lacking"


def questions_for(level: str) -> List[Dict[str, Any]]:
    out = []
    for q in seed.QUESTIONS:
        if level not in q[2]:
            continue
        statement = seed.STATEMENT_VARIANTS.get(q[0], {}).get(level, q[3])
        out.append({"id": q[0], "dimension": q[1], "statement": statement,
                    "role_specific": q[0] in seed.STATEMENT_VARIANTS or len(q[2]) == 1,
                    "anchors": seed.anchors_for(statement)})
    return out


def dimensions() -> List[Dict[str, Any]]:
    return [{"id": d[0], "name": d[1], "iso_56001_clauses": d[2],
             "weight": seed.WEIGHTS[d[0]]} for d in seed.DIMENSIONS]


def create_campaign(name: str, is_anonymous: bool) -> Dict[str, Any]:
    with db._conn() as conn:
        _tbl(conn)
        cur = conn.execute("INSERT INTO audit_campaigns (name, is_anonymous, created_at) "
                           "VALUES (?, ?, ?)", (name, int(is_anonymous), db._now()))
        return {"id": cur.lastrowid, "name": name, "is_anonymous": is_anonymous}


def campaigns() -> List[Dict[str, Any]]:
    with db._conn() as conn:
        _tbl(conn)
        return [dict(r) for r in conn.execute("SELECT * FROM audit_campaigns ORDER BY id")]


def invite(campaign_id: int, person: str, level: str, org_unit: str) -> None:
    with db._conn() as conn:
        _tbl(conn)
        conn.execute("INSERT INTO audit_invitations (campaign_id, person, level, org_unit) "
                     "VALUES (?, ?, ?, ?)", (campaign_id, person, level, org_unit))


def submit(campaign_id: int, level: str, org_unit: str, respondent: Optional[str],
           items: List[Dict[str, Any]]) -> None:
    camp = next((c for c in campaigns() if c["id"] == campaign_id), None)
    if camp is None:
        raise ValueError("campaign not found")
    allowed = {q["id"] for q in questions_for(level)}
    for it in items:
        if it["question"] not in allowed:
            raise ValueError(f"question {it['question']} not applicable to level {level}")
        if not it.get("is_na") and not (0 <= int(it["score"]) <= 4):
            raise ValueError("scores are 0-4")
    with db._conn() as conn:
        _tbl(conn)
        conn.execute("INSERT INTO audit_responses (campaign_id, level, org_unit, respondent, "
                     "submitted_at, items) VALUES (?, ?, ?, ?, ?, ?)",
                     (campaign_id, level, org_unit,
                      None if camp["is_anonymous"] else respondent, db._now(),
                      json.dumps(items)))
        conn.execute("UPDATE audit_invitations SET status='completed' WHERE campaign_id=? "
                     "AND person=? AND status!='completed'", (campaign_id, respondent or ""))


def _responses(campaign_id: int) -> List[Dict[str, Any]]:
    with db._conn() as conn:
        _tbl(conn)
        return [{**dict(r), "items": json.loads(r["items"])} for r in conn.execute(
            "SELECT * FROM audit_responses WHERE campaign_id=?", (campaign_id,))]


def _dim_score(items: List[Dict[str, Any]], dim: str) -> Optional[float]:
    xs = [int(i["score"]) for i in items
          if i["question"].startswith(dim + ".") and not i.get("is_na")]
    return round(sum(xs) / len(xs) * 25, 1) if xs else None


def results(campaign_id: int) -> Dict[str, Any]:
    camp = next((c for c in campaigns() if c["id"] == campaign_id), None)
    cfg = config(camp)
    resp = _responses(campaign_id)
    with db._conn() as conn:
        _tbl(conn)
        inv = [dict(r) for r in conn.execute(
            "SELECT level, status FROM audit_invitations WHERE campaign_id=?", (campaign_id,))]
    dims_out = []
    gaps = []
    for d in dimensions():
        overall = [s for s in (_dim_score(r["items"], d["id"]) for r in resp) if s is not None]
        by_level = {}
        for lv in LEVELS:
            seg = [r for r in resp if r["level"] == lv]
            ss = [s for s in (_dim_score(r["items"], d["id"]) for r in seg) if s is not None]
            by_level[lv] = {"n": len(seg),
                            "score": (round(sum(ss) / len(ss), 1)
                                      if ss and len(seg) >= cfg["min_segment_n"] else None),
                            "suppressed": bool(ss) and len(seg) < cfg["min_segment_n"]}
        pair, gap = None, 0.0
        vals = {lv: v["score"] for lv, v in by_level.items() if v["score"] is not None}
        for a, b in combinations(vals, 2):
            g = abs(vals[a] - vals[b])
            if g > gap:
                gap, pair = g, (a, b)
        score = round(sum(overall) / len(overall), 1) if overall else None
        dims_out.append({**d, "score": score,
                         "band": band(score, cfg) if score is not None else None,
                         "by_level": by_level, "gap": round(gap, 1), "gap_pair": pair,
                         "gap_flagged": gap >= cfg["gap_threshold"]})
        if gap >= cfg["gap_threshold"] and pair:
            gaps.append({"dimension": d["id"], "name": d["name"], "gap": round(gap, 1),
                         "levels": pair})
    scored = [d for d in dims_out if d["score"] is not None]
    total_w = sum(cfg["weights"][d["id"]] for d in scored) or 1
    composite = round(sum(d["score"] * cfg["weights"][d["id"]] for d in scored) / total_w, 1) \
        if scored else None
    return {"campaign": camp, "config": cfg, "dimensions": dims_out,
            "composite": composite,
            "band": band(composite, cfg) if composite is not None else None,
            "flagged_gaps": gaps,
            "response_rate": {"invited": len(inv),
                              "completed": sum(1 for i in inv if i["status"] == "completed"),
                              "responses": len(resp)},
            "note": f"Segments with fewer than {cfg['min_segment_n']} respondents are "
                    "suppressed but still roll into totals."}


def generate_roadmap(campaign_id: int) -> List[Dict[str, Any]]:
    res = results(campaign_id)
    cfg = res["config"]
    with db._conn() as conn:
        _tbl(conn)
        existing = {(r["template_id"], r["dimension"]) for r in conn.execute(
            "SELECT template_id, dimension FROM audit_roadmap WHERE campaign_id=?",
            (campaign_id,))}
        for d in res["dimensions"]:
            if d["score"] is None or d["score"] >= cfg["readiness"]:
                continue
            for tid, dim, lo, hi, title, eff, imp, hz in seed.RECOMMENDATION_TEMPLATES:
                if dim == d["id"] and lo <= d["score"] <= hi and (tid, dim) not in existing:
                    pr = max(0, cfg["readiness"] - d["score"]) * IMPACT[imp] / EFFORT[eff]
                    conn.execute(
                        "INSERT INTO audit_roadmap (campaign_id, template_id, dimension, title, "
                        "description, horizon, priority, kpi) VALUES (?,?,?,?,?,?,?,?)",
                        (campaign_id, tid, dim, title,
                         f"Triggered: {d['name']} scored {d['score']} ({d['band']}).",
                         hz, round(pr, 1), f"{d['name']} score at next audit"))
        gid, gtitle, gdesc, geff, gimp, ghz = seed.GAP_TEMPLATE
        for g in res["flagged_gaps"]:
            if (gid, g["dimension"]) in existing:
                continue
            dscore = next(d["score"] for d in res["dimensions"] if d["id"] == g["dimension"])
            pr = max(0, cfg["readiness"] - (dscore or 0)) * IMPACT[gimp] / EFFORT[geff]
            conn.execute(
                "INSERT INTO audit_roadmap (campaign_id, template_id, dimension, title, "
                "description, horizon, priority, kpi) VALUES (?,?,?,?,?,?,?,?)",
                (campaign_id, gid, g["dimension"],
                 gtitle.format(dimension_name=g["name"]),
                 gdesc.format(dimension_name=g["name"], gap=g["gap"],
                              level_a=g["levels"][0], level_b=g["levels"][1]),
                 ghz, round(pr, 1), f"Gap on {g['name']} at next audit cycle"))
    return roadmap(campaign_id)


def roadmap(campaign_id: int) -> List[Dict[str, Any]]:
    with db._conn() as conn:
        _tbl(conn)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_roadmap WHERE campaign_id=? ORDER BY priority DESC",
            (campaign_id,))]


def update_roadmap_item(item_id: int, patch: Dict[str, Any]) -> None:
    cols = {k: v for k, v in patch.items()
            if k in ("status", "horizon", "title", "description", "owner", "due_date")}
    if not cols:
        return
    with db._conn() as conn:
        conn.execute(f"UPDATE audit_roadmap SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?",
                     [*cols.values(), item_id])


def value_index() -> Dict[str, Any]:
    """0-100 Value Realization Index from existing outcome metrics.
    Default mapping (documented, configurable via meta 'value_index_config'):
      50% realization ratio  = (verified+claimed) / released investment, target 1.0
      30% verified intensity = verified annual value / $100k target
      20% funnel conversion  = ideas -> business-case rate, target 25%"""
    period = db._now()[:7]
    with db._conn() as conn:
        _tbl(conn)
        row = conn.execute("SELECT * FROM value_index_snapshots WHERE period=?",
                           (period,)).fetchone()
        if row and row["source"] == "manual":
            return {"value": row["value"], "source": "manual", "period": period}
    cases = db.list_business_cases()
    ideas = db.list_ideas()
    released = sum((c.get("funding") or {}).get("released", 0) for c in cases)
    verified = sum((b.get("annualized_delta") or 0)
                   for c in cases for b in c.get("metric_bindings", []))
    claimed = sum(e["amount"] for c in cases for e in c.get("savings_entries", []))
    r1 = min((verified + claimed) / released, 1.0) if released else 0
    r2 = min(verified / 100000, 1.0)
    r3 = min((len(cases) / len(ideas)) / 0.25, 1.0) if ideas else 0
    v = round((0.5 * r1 + 0.3 * r2 + 0.2 * r3) * 100, 1)
    with db._conn() as conn:
        conn.execute("INSERT OR REPLACE INTO value_index_snapshots (period, value, source) "
                     "VALUES (?, ?, 'computed')", (period, v))
    return {"value": v, "source": "computed", "period": period,
            "components": {"realization_ratio": round(r1, 2),
                           "verified_intensity": round(r2, 2), "funnel_conversion": round(r3, 2)}}


def set_manual_value_index(value: float) -> Dict[str, Any]:
    period = db._now()[:7]
    with db._conn() as conn:
        _tbl(conn)
        conn.execute("INSERT OR REPLACE INTO value_index_snapshots (period, value, source) "
                     "VALUES (?, ?, 'manual')", (period, value))
    return {"value": value, "source": "manual", "period": period}


def seed_demo() -> None:
    if campaigns():
        return
    c = create_campaign("Baseline audit (Q3)", is_anonymous=False)
    import random
    random.seed(11)
    people = [("elena", "executive", "Corporate"), ("marcus", "executive", "Corporate"),
              ("dana", "executive", "Ops"),
              ("jordan", "management", "Ops"), ("priya", "management", "Digital"),
              ("li", "management", "Corporate"),
              ("sam", "practitioner", "Ops"), ("alex", "practitioner", "Digital"),
              ("kim", "practitioner", "Digital")]
    # executives systematically rosier on D5 (culture) => perception gap
    bias = {"executive": 1, "management": 0, "practitioner": 0}
    base = {"D1": 2, "D2": 2, "D3": 2, "D4": 1, "D5": 2, "D6": 1, "D7": 2, "D8": 1}
    for person, level, org in people:
        invite(c["id"], person, level, org)
        items = []
        for q in questions_for(level):
            b = base[q["dimension"]] + (bias[level] if q["dimension"] in ("D5", "D4") else 0)
            extra = 1 if level == "executive" and q["dimension"] == "D5" else 0
            items.append({"question": q["id"],
                          "score": max(0, min(4, b + extra + random.choice([0, 0, 1]))),
                          "is_na": False})
        submit(c["id"], level, org, person, items)
    generate_roadmap(c["id"])
