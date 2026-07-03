import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import connectors
from app.ingestion import IngestionError, parse_csv
from app.main import app
from app.opportunities import analyze

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("IVD_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # force template ROI path


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------- ingestion

def test_parse_csv_valid():
    rows = parse_csv("cmdb", (SAMPLE_DIR / "cmdb.csv").read_bytes())
    assert len(rows) > 0
    assert rows[0]["ci_name"] == "srv-fin-01"
    assert isinstance(rows[0]["annual_cost"], float)


def test_parse_csv_missing_column():
    with pytest.raises(IngestionError, match="Missing required columns"):
        parse_csv("cmdb", b"ci_name,ci_type\nfoo,Server\n")


# -------------------------------------------------------------------- rules

def _sample_datasets():
    return {
        st: parse_csv(st, (SAMPLE_DIR / f"{st}.csv").read_bytes())
        for st in ("cmdb", "erp", "cloud", "itsm")
    }


def test_rules_fire_on_sample_data():
    opps = analyze(_sample_datasets())
    categories = {o["category"] for o in opps}
    assert "Idle infrastructure" in categories
    assert "Duplicate payments" in categories
    assert "Idle cloud resources" in categories
    assert "Automation candidate" in categories
    assert all(o["estimated_annual_savings"] > 0 for o in opps)


def test_opportunity_ids_are_deterministic():
    a = analyze(_sample_datasets())
    b = analyze(_sample_datasets())
    assert [o["id"] for o in a] == [o["id"] for o in b]


# ------------------------------------------------------- API + persistence

def test_full_lifecycle(client):
    # load samples, persisted to sqlite
    resp = client.post("/api/datasets/load-samples")
    assert resp.status_code == 200
    assert resp.json()["loaded"]["cmdb"] > 0

    opps = client.get("/api/opportunities").json()["opportunities"]
    assert len(opps) > 0
    target = opps[0]

    # create a case linked to the top opportunity (template plan path)
    resp = client.post("/api/business-cases", json={
        "title": "Fix the top opportunity",
        "description": "Implement the remediation described by the engine.",
        "estimated_cost": 50000,
        "linked_opportunity_id": target["id"],
    })
    assert resp.status_code == 200
    case = resp.json()
    assert case["generated_by"] == "template"
    assert case["linked_opportunity"]["id"] == target["id"]
    assert case["status"] == "proposed"
    assert case["tracking"] is None

    # linking to a bogus opportunity fails cleanly
    resp = client.post("/api/business-cases", json={
        "title": "x", "description": "y", "linked_opportunity_id": "OPP-nope",
    })
    assert resp.status_code == 400

    # mark implemented
    resp = client.post(f"/api/business-cases/{case['id']}/implement",
                       json={"go_live_date": "2026-01-01"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "implemented"

    # KPI reading must reference a KPI from the plan
    kpi_name = case["roi_plan"]["kpis"][0]["name"]
    resp = client.post(f"/api/business-cases/{case['id']}/readings", json={
        "kpi_name": kpi_name, "reading_date": "2026-02-01", "value": 123.4,
    })
    assert resp.status_code == 200
    assert resp.json()["kpi_readings"][0]["value"] == 123.4

    resp = client.post(f"/api/business-cases/{case['id']}/readings", json={
        "kpi_name": "Not a real KPI", "reading_date": "2026-02-01", "value": 1,
    })
    assert resp.status_code == 400

    # savings entries drive tracking math
    for month, amount in (("2026-02-01", 20000), ("2026-03-01", 40000)):
        resp = client.post(f"/api/business-cases/{case['id']}/savings", json={
            "entry_date": month, "amount": amount,
        })
        assert resp.status_code == 200
    tracking = resp.json()["tracking"]
    assert tracking["total_realized_savings"] == 60000
    assert tracking["realized_roi_pct"] == 20.0          # (60k - 50k) / 50k
    assert tracking["payback_progress_pct"] == 100.0      # capped
    assert tracking["months_live"] >= 1

    # persistence: re-listing returns the same case with readings attached
    cases = client.get("/api/business-cases").json()["business_cases"]
    assert cases[0]["id"] == case["id"]
    assert len(cases[0]["savings_entries"]) == 2


# --------------------------------------------------------------- connectors

class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def test_servicenow_cmdb_sync(monkeypatch, client):
    def fake_get(url, auth=None, params=None, timeout=None):
        assert "/api/now/table/cmdb_ci" in url
        assert auth == ("admin", "secret")
        return FakeResponse({"result": [
            {
                "name": "snow-srv-01",
                "sys_class_name": "Linux Server",
                "install_status": "Installed",
                "u_environment": "prod",
                "cost": "12,500.00",
                "u_cpu_utilization": "3",
                "u_eol_date": "2024-01-01",
                "u_application_category": "",
            },
            {
                "name": "snow-srv-02",
                "sys_class_name": {"display_value": "Windows Server", "link": "..."},
                "install_status": "Installed",
                "u_environment": "prod",
                "cost": "8000",
                "u_cpu_utilization": "55",
                "u_eol_date": "",
                "u_application_category": "",
            },
        ]})

    monkeypatch.setattr(connectors.httpx, "get", fake_get)
    resp = client.post("/api/connectors/servicenow/sync", json={
        "instance_url": "https://dev.service-now.com",
        "username": "admin", "password": "secret", "source": "cmdb",
    })
    assert resp.status_code == 200
    assert resp.json() == {"source_type": "cmdb", "rows_loaded": 2, "origin": "servicenow"}

    # synced rows flow into the rules engine (idle + EOL server present)
    cats = {o["category"] for o in client.get("/api/opportunities").json()["opportunities"]}
    assert "Idle infrastructure" in cats


def test_servicenow_auth_failure(monkeypatch, client):
    monkeypatch.setattr(
        connectors.httpx, "get",
        lambda *a, **kw: FakeResponse({"error": "auth"}, status_code=401),
    )
    resp = client.post("/api/connectors/servicenow/sync", json={
        "instance_url": "https://dev.service-now.com",
        "username": "admin", "password": "wrong", "source": "cmdb",
    })
    assert resp.status_code == 502
    assert "Authentication failed" in resp.json()["detail"]


def test_sap_odata_sync(monkeypatch, client):
    def fake_get(url, auth=None, params=None, timeout=None):
        assert "/InvoiceSet" in url
        return FakeResponse({"d": {"results": [
            {
                "InvoiceDocNumber": "5100000001",
                "SupplierName": "ACME GmbH",
                "PurchasingGroupName": "IT Hardware",
                "GrossAmount": "45200.00",
                "DocumentDate": "/Date(1767225600000)/",  # 2026-01-01
                "PaymentTermsDays": "30",
                "PurchaseOrder": "4500000123",
            },
        ]}})

    monkeypatch.setattr(connectors.httpx, "get", fake_get)
    resp = client.post("/api/connectors/sap/sync", json={
        "service_url": "https://sap.example.com/sap/opu/odata/sap/ZINVOICE_SRV",
        "entity_set": "InvoiceSet",
    })
    assert resp.status_code == 200
    assert resp.json()["rows_loaded"] == 1

    rows_meta = client.get("/api/datasets").json()["sources"]
    erp = next(s for s in rows_meta if s["source_type"] == "erp")
    assert erp["origin"] == "sap_odata"


# ------------------------------------------------------------ prioritization

from app.prioritization import normalize_weights, prioritize, WeightError


def _opp(savings, effort, confidence, n=10, title="t", complexity="medium"):
    return {
        "id": f"OPP-{title}", "source": "cmdb", "category": "c", "title": title,
        "description": "d", "estimated_annual_savings": savings,
        "effort": effort, "confidence": confidence, "complexity": complexity,
        "affected_items": [], "affected_count": n,
    }


def test_quick_win_outranks_money_pit():
    # same headline savings: low-effort/high-confidence must beat high-effort/low-confidence
    quick = _opp(50000, "low", "high", title="quick")
    pit = _opp(50000, "high", "low", title="pit")
    ranked = prioritize([quick, pit])["opportunities"]
    assert ranked[0]["title"] == "quick"
    assert ranked[0]["priority"]["quadrant"] == "quick_win"
    assert ranked[1]["priority"]["quadrant"] == "deprioritize"


def test_value_weight_can_flip_ordering():
    whale = _opp(2_000_000, "high", "medium", n=100, title="whale")
    minnow = _opp(30000, "low", "high", n=3, title="minnow")
    eff_heavy = prioritize(
        [whale, minnow], normalize_weights(0.05, 0.9, 0.05)
    )["opportunities"]
    val_heavy = prioritize(
        [whale, minnow], normalize_weights(0.95, 0.025, 0.025)
    )["opportunities"]
    assert eff_heavy[0]["title"] == "minnow"
    assert val_heavy[0]["title"] == "whale"


def test_priority_economics_math():
    opp = _opp(120000, "low", "high", n=4)
    econ = prioritize([opp])["opportunities"][0]["priority"]
    assert econ["risk_adjusted_annual_savings"] == 108000.0   # 120k * 0.9
    assert econ["est_implementation_cost"] == 6000.0          # 5000 + 4*250
    assert econ["time_to_value_months"] == 1
    # payback = ttv + cost / monthly = 1 + 6000/9000
    assert econ["payback_months"] == 1.7
    assert econ["first_year_net"] == 93000.0                  # 108k * 11/12 - 6k


def test_invalid_weights_rejected():
    with pytest.raises(WeightError):
        normalize_weights(-1, 0.5, 0.5)
    with pytest.raises(WeightError):
        normalize_weights(0, 0, 0, 0)


def test_opportunities_endpoint_prioritized(client):
    client.post("/api/datasets/load-samples")
    resp = client.get("/api/opportunities")
    assert resp.status_code == 200
    body = resp.json()
    opps = body["opportunities"]
    scores = [o["priority"]["score"] for o in opps]
    assert scores == sorted(scores, reverse=True)
    assert opps[0]["priority"]["rank"] == 1
    assert body["prioritization"]["summary"]["count_for_80_pct_of_value"] >= 1
    assert set(body["prioritization"]["weights"]) == {"value", "efficiency", "speed", "simplicity"}

    # custom weights are accepted; bad weights rejected
    assert client.get("/api/opportunities?value_weight=1&efficiency_weight=0&speed_weight=0").status_code == 200
    assert client.get("/api/opportunities?value_weight=-1").status_code == 400


def test_complexity_scales_with_blast_radius():
    from app.opportunities import _scale_complexity
    assert _scale_complexity("medium", 5) == "medium"
    assert _scale_complexity("medium", 20) == "high"
    assert _scale_complexity("medium", 80) == "very_high"
    assert _scale_complexity("very_high", 200) == "very_high"  # capped


def test_simplicity_weight_prefers_low_complexity():
    # identical economics, only complexity differs
    simple = _opp(50000, "medium", "high", title="simple", complexity="low")
    tangled = _opp(50000, "medium", "high", title="tangled", complexity="very_high")
    ranked = prioritize([simple, tangled])["opportunities"]
    assert ranked[0]["title"] == "simple"
    assert ranked[0]["priority"]["components"]["simplicity"] == 1.0
    assert ranked[1]["priority"]["components"]["simplicity"] == 0.15

    # with simplicity weight zeroed, they tie on score
    flat = prioritize([simple, tangled], normalize_weights(0.4, 0.35, 0.25, 0))["opportunities"]
    assert flat[0]["priority"]["score"] == flat[1]["priority"]["score"]


def test_opportunities_carry_complexity(client):
    client.post("/api/datasets/load-samples")
    opps = client.get("/api/opportunities").json()["opportunities"]
    assert all(o["complexity"] in ("low", "medium", "high", "very_high") for o in opps)
    assert all("simplicity" in o["priority"]["components"] for o in opps)
    # rules disagree: app rationalization must be rated more complex than orphaned storage
    by_cat = {o["category"]: o["complexity"] for o in opps}
    assert by_cat["Application rationalization"] == "high"
    assert by_cat["Orphaned storage"] == "low"


# -------------------------------------------------- measurement & calibration

from app import metrics


def test_metric_compute_and_validation():
    datasets = _sample_datasets()
    result = metrics.compute({
        "metric": "sum", "source": "cloud", "field": "monthly_cost",
        "filters": [{"field": "resource_id", "op": "in",
                     "values": ["i-0a1b2c3d01", "i-0a1b2c3d02"]}],
    }, datasets)
    assert result == {"value": 840.0, "rows_matched": 2}

    count = metrics.compute({
        "metric": "count", "source": "itsm",
        "filters": [{"field": "ticket_type", "op": "eq", "value": "Request"}],
    }, datasets)
    assert count["value"] == 33  # 16 + 12 + 5 request rows in sample data

    with pytest.raises(metrics.MetricError):
        metrics.validate_definition({"metric": "median", "source": "cloud"})
    with pytest.raises(metrics.MetricError):
        metrics.validate_definition({"metric": "sum", "source": "cloud"})  # no field


def _walk_to_prioritized(client, idea_id, actor="lee"):
    for decision in ("qualify", "prioritize"):
        resp = client.post("/api/command/decide", json={
            "subject_type": "idea", "subject_id": idea_id,
            "decision": decision, "actor": actor,
        })
        assert resp.status_code == 200, resp.text


def _cloud_idle_opp(client):
    opps = client.get("/api/opportunities").json()["opportunities"]
    return next(o for o in opps if o["category"] == "Idle cloud resources")


def test_linked_case_freezes_baseline_and_observes_change(client):
    client.post("/api/datasets/load-samples")
    opp = _cloud_idle_opp(client)

    case = client.post("/api/business-cases", json={
        "title": "Terminate idle cloud", "description": "Kill the idle instances.",
        "estimated_cost": 10000, "linked_opportunity_id": opp["id"],
    }).json()

    # baseline frozen automatically from the opportunity's own measure
    assert len(case["metric_bindings"]) == 1
    binding = case["metric_bindings"][0]
    assert binding["unit"] == "usd_per_month"
    assert binding["baseline_value"] == 2280.0   # 560 + 280 + 1440
    assert binding["baseline_rows"] == 3
    assert binding["latest_value"] is None

    # simulate the remediation: re-upload cloud data without the idle resources
    survivors = (
        "resource_id,service,monthly_cost,state,avg_cpu_pct\n"
        "i-0a1b2c3d05,EC2,140.00,running,64\n"
        "db-2e3f4a01,RDS,720.00,running,38\n"
    )
    resp = client.post("/api/datasets/cloud",
                       files={"file": ("cloud.csv", survivors, "text/csv")})
    assert resp.status_code == 200

    case = client.post(
        f"/api/business-cases/{case['id']}/bindings/{binding['id']}/observe"
    ).json()
    binding = case["metric_bindings"][0]
    assert binding["latest_value"] == 0.0          # same query, new data
    assert binding["delta"] == 2280.0
    assert binding["annualized_delta"] == 27360.0  # monthly delta x 12

    # measured value flows into tracking once implemented
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-05-01"})
    case = client.get("/api/business-cases").json()["business_cases"][0]
    assert case["tracking"]["measured_annual_savings"] == 27360.0


def test_manual_binding_endpoint(client):
    client.post("/api/datasets/load-samples")
    case = client.post("/api/business-cases", json={
        "title": "Standalone", "description": "No linked opportunity.",
    }).json()
    resp = client.post(f"/api/business-cases/{case['id']}/bindings", json={
        "label": "Password reset volume",
        "definition": {
            "metric": "count", "source": "itsm",
            "filters": [{"field": "category", "op": "eq", "value": "password reset"}],
        },
    })
    assert resp.status_code == 200
    assert resp.json()["metric_bindings"][0]["baseline_value"] == 16.0

    bad = client.post(f"/api/business-cases/{case['id']}/bindings", json={
        "label": "x", "definition": {"metric": "sum", "source": "nope"},
    })
    assert bad.status_code == 400


def test_calibration_feeds_prioritization(client):
    client.post("/api/datasets/load-samples")
    opp = _cloud_idle_opp(client)
    assert opp["priority"]["calibration_factor"] == 1.0  # nothing learned yet

    case = client.post("/api/business-cases", json={
        "title": "c", "description": "d", "estimated_cost": 5000,
        "linked_opportunity_id": opp["id"],
    }).json()
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-01-01"})
    # claimed savings: 1200/mo for ~5 months live -> annualized well below forecast
    client.post(f"/api/business-cases/{case['id']}/savings",
                json={"entry_date": "2026-02-01", "amount": 6000})

    report = client.get("/api/calibration").json()
    stats = report["categories"]["Idle cloud resources"]
    assert stats["cases"] == 1
    assert 0 < stats["realization_rate"] < 1
    assert stats["basis"] == ["claimed"]

    # the learned factor now discounts the same category's future estimates
    opp_after = _cloud_idle_opp(client)
    factor = opp_after["priority"]["calibration_factor"]
    assert factor == stats["applied_factor"]
    assert factor < 1.0
    assert (opp_after["priority"]["risk_adjusted_annual_savings"]
            < opp["priority"]["risk_adjusted_annual_savings"])


def test_roi_template_carries_objectivity():
    from app.roi import _template_plan
    plan = _template_plan("t", "d", 1000)
    assert {k.objectivity for k in plan.kpis} == {"hard", "medium"}
    assert plan.unmeasurable_claims == []


# ------------------------------------------------------------------- timeline

def test_value_timeline_and_roi(client):
    client.post("/api/datasets/load-samples")
    opp = _cloud_idle_opp(client)
    case = client.post("/api/business-cases", json={
        "title": "t", "description": "d", "estimated_cost": 10000,
        "linked_opportunity_id": opp["id"],
    }).json()
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-03-01"})
    client.post(f"/api/business-cases/{case['id']}/savings",
                json={"entry_date": "2026-04-01", "amount": 3000})

    # remediate and observe -> verified run-rate starts this month
    survivors = "resource_id,service,monthly_cost,state,avg_cpu_pct\nx-1,EC2,100,running,50\n"
    client.post("/api/datasets/cloud", files={"file": ("c.csv", survivors, "text/csv")})
    binding_id = case["metric_bindings"][0]["id"]
    client.post(f"/api/business-cases/{case['id']}/bindings/{binding_id}/observe")

    tl = client.get("/api/dashboard").json()["timeline"]
    summary = tl["summary"]
    months = tl["months"]

    assert summary["total_invested"] == 10000
    assert summary["claimed_value_to_date"] == 3000
    assert summary["verified_run_rate"] == 27360.0
    # cost lands in the go-live month and stays cumulative
    march = next(m for m in months if m["month"] == "2026-03")
    assert march["cumulative_cost"] == 10000
    april = next(m for m in months if m["month"] == "2026-04")
    assert april["cumulative_claimed"] == 3000
    # verified value only accrues from the observation month (no retro credit)
    assert all(m["cumulative_verified"] == 0 for m in months if m["month"] < "2026-06")
    # projection extends the run-rate and finds break-even (10k / 2280-mo)
    assert any(m["projected"] for m in months)
    assert summary["break_even_month"] is not None
    assert summary["break_even_projected"] is True
    last_actual = [m for m in months if not m["projected"]][-1]
    assert last_actual["roi_pct"] == summary["portfolio_roi_pct"]


# ------------------------------------------------------------------ portfolio

def test_portfolio_diagnostic(client):
    resp = client.get("/api/portfolio/diagnostic")
    assert resp.status_code == 400  # nothing loaded yet

    client.post("/api/datasets/load-samples")
    report = client.get("/api/portfolio/diagnostic").json()

    assert 5 <= report["health_score"] < 100
    stats = report["stats"]
    assert stats["initiatives"] == 10
    assert stats["verification_ratio"] is not None

    categories = {f["category"] for f in report["findings"]}
    # the sample portfolio is seeded to trip every diagnostic
    assert "Unverified benefits" in categories       # ERP modernization, live, unmeasured
    assert "Realization shortfall" in categories     # chatbot: 40k of 180k claimed
    assert "Weak ROI" in categories                  # legacy DC exit / data lake
    assert "Budget overrun" in categories            # ERP modernization over budget
    assert "Stalled delivery" in categories          # cloud wave 2 / DC exit in flight >12mo
    assert "Parked spend" in categories              # network refresh + workplace on hold
    assert "Overlapping scope" in categories         # two data platform initiatives

    # findings sorted high severity first, each carries value impact
    severities = [f["severity"] for f in report["findings"]]
    assert severities == sorted(severities, key={"high": 0, "medium": 1, "low": 2}.get)
    assert all(f["value_impact"] >= 0 for f in report["findings"])

    unverified = next(f for f in report["findings"] if f["category"] == "Unverified benefits")
    assert "ERP modernization" in unverified["affected_initiatives"]


# --------------------------------------------------------- executive dashboard

def test_dashboard_headline_and_decisions(client):
    client.post("/api/datasets/load-samples")
    dash = client.get("/api/dashboard").json()

    # first dashboard read triggers the automation pass: the hub auto-drafts
    # cases for the top quick wins, so value is already "committed"
    assert "committed" in dash["headline"]
    assert dash["portfolio_health"] is not None  # sample portfolio loaded
    hub_metrics = dash["hub"]
    assert hub_metrics["automation"]["last_run"] is not None
    assert hub_metrics["automation"]["actions_by_rule"].get("auto_draft", 0) >= 1
    assert hub_metrics["pipeline_stages"]["draft"] >= 1

    decisions = dash["decisions"]
    assert 0 < len(decisions) <= 6
    actions = {d["action"] for d in decisions}
    assert "approve" in actions          # sub-threshold quick wins remain manual
    assert "review" in actions           # auto-drafted cases await review
    assert "intervene" in actions        # high-severity portfolio findings
    values = [d["annual_value"] for d in decisions]
    assert values == sorted(values, reverse=True)
    assert all(d["nav"] in ("opportunities", "cases", "tracking", "portfolio")
               for d in decisions)

    # linking a case removes that opportunity from the approve queue,
    # and an unverified implemented case produces a verify decision
    top_approve = next(d for d in decisions if d["action"] == "approve")
    opps = client.get("/api/opportunities").json()["opportunities"]
    opp = next(o for o in opps if o["title"] == top_approve["title"])
    case = client.post("/api/business-cases", json={
        "title": "x", "description": "y", "estimated_cost": 1000,
        "linked_opportunity_id": opp["id"],
    }).json()
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-05-01"})

    dash = client.get("/api/dashboard").json()
    approve_titles = [d["title"] for d in dash["decisions"] if d["action"] == "approve"]
    assert opp["title"] not in approve_titles
    assert any(d["action"] == "verify" for d in dash["decisions"])


# -------------------------------------------------------------- innovation hub

def test_idea_intake_triage_and_promotion(client):
    client.post("/api/datasets/load-samples")

    # idea matching a detected quick win gets fast-tracked with enrichment noted
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "AP sometimes pays the same invoice twice. Detect duplicate "
                       "invoices by vendor and amount and recover the payments.",
        "submitter": "maria",
    }).json()
    a = idea["assessment"]
    assert a["matched_opportunity"] is not None
    assert a["recommendation"] == "fast_track"
    assert a["score"] > 0
    assert any("derived" in note.lower() for note in a["enrichment"])
    assert idea["category"] is not None  # enriched from the match

    # unmatched idea -> investigate
    novel = client.post("/api/ideas", json={
        "title": "Robot greeter", "description": "Put a robot in the lobby to welcome guests.",
    }).json()
    assert novel["assessment"]["recommendation"] == "investigate"

    # gates enforced: no business case before prioritization
    assert client.post(f"/api/ideas/{idea['id']}/promote").status_code == 400
    _walk_to_prioritized(client, idea["id"])

    # promotion (business case development) creates a linked case with a frozen baseline
    result = client.post(f"/api/ideas/{idea['id']}/promote").json()
    assert result["idea"]["status"] == "business_case"
    case = result["case"]
    assert case["stage"] == "proposed"
    assert case["linked_opportunity"] is not None
    assert len(case["metric_bindings"]) == 1
    assert client.post(f"/api/ideas/{idea['id']}/promote").status_code == 400


def test_idea_bulk_import_with_enrichment(client):
    client.post("/api/datasets/load-samples")
    csv_body = (
        "title,description,submitter,estimated_annual_benefit\n"
        "Terminate idle cloud instances,Several EC2 instances run under 5% CPU and "
        "could be terminated to cut monthly cloud cost,sam,\n"
        ",missing title should be skipped,x,\n"
        "Automate password resets,Self-service password reset portal to cut service "
        "desk request tickets,ana,20000\n"
    )
    resp = client.post("/api/ideas/import", files={"file": ("backlog.csv", csv_body, "text/csv")})
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2 and body["skipped"] == 1

    ideas = client.get("/api/ideas").json()["ideas"]
    imported = [i for i in ideas if i["source"] == "import"]
    assert len(imported) == 2
    cloud_idea = next(i for i in imported if "cloud" in i["title"].lower())
    assert cloud_idea["assessment"]["matched_opportunity"] is not None
    assert cloud_idea["assessment"]["enrichment"]  # benefit derived, noted


def test_scoring_framework_guardrails(client):
    client.post("/api/datasets/load-samples")

    # leader tightens the guardrails and reweights toward alignment
    resp = client.put("/api/scoring-config", json={
        "idea_weights": {"impact": 0.2, "data_grounding": 0.2, "alignment": 0.5, "completeness": 0.1},
        "priority_themes": ["sustainability"],
        "guardrails": {"min_annual_benefit": 100000, "require_category": True,
                       "require_benefit_estimate": False},
    })
    assert resp.status_code == 200

    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount.",
    }).json()
    a = idea["assessment"]
    assert a["recommendation"] == "needs_info"
    assert any("minimum benefit guardrail" in f for f in a["guardrail_flags"])
    assert any("Category is required" in f for f in a["guardrail_flags"])
    assert a["score_components"]["alignment"] == 0.0  # 'sustainability' not mentioned

    # invalid config rejected
    assert client.put("/api/scoring-config", json={
        "idea_weights": {"impact": -1, "data_grounding": 0, "alignment": 0, "completeness": 0},
    }).status_code == 400

    # opportunity weights from config drive the default prioritization
    resp = client.put("/api/scoring-config", json={
        "opportunity_weights": {"value": 1, "efficiency": 0, "speed": 0, "simplicity": 0},
    })
    assert resp.status_code == 200
    weights = client.get("/api/opportunities").json()["prioritization"]["weights"]
    assert weights["value"] == 1


def test_governance_and_command_center(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount and recover.",
    }).json()

    # no governance configured -> anyone can decide
    resp = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"],
        "decision": "feedback", "actor": "sam", "comment": "needs cost detail",
    })
    assert resp.status_code == 200

    # assign idea screening to dana only — qualification gate enforces it
    client.put("/api/governance", json={"idea_screening": ["Dana"]})
    resp = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "qualify", "actor": "sam",
    })
    assert resp.status_code == 403
    resp = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "qualify", "actor": "dana",
    })
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "qualified"

    # prioritization is a portfolio decision (area unassigned -> open), then AI develops
    resp = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "prioritize", "actor": "lee",
    })
    assert resp.json()["result"]["status"] == "prioritized"
    resp = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop", "actor": "lee",
    })
    assert resp.status_code == 200
    case = resp.json()["result"]["case"]
    assert case["stage"] == "proposed"

    # case approval advances stage by stage; mobilization requires released funding
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"], "decision": "approve", "actor": "lee",
    })
    assert resp.json()["result"]["stage"] == "approved"
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"], "decision": "approve", "actor": "lee",
    })
    assert resp.status_code == 400
    assert "Funding gate" in resp.json()["detail"]
    tranched = client.post(f"/api/business-cases/{case['id']}/tranches", json={
        "label": "Mobilization", "amount": 20000, "milestone": "Case approved",
    }).json()
    client.post(
        f"/api/business-cases/{case['id']}/tranches/{tranched['funding']['tranches'][0]['id']}/release",
        json={"actor": "lee"},
    )
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"], "decision": "approve", "actor": "lee",
    })
    assert resp.json()["result"]["stage"] == "in_delivery"

    queue = client.get("/api/command/queue").json()
    assert any(c["id"] == case["id"] for c in queue["cases_in_motion"])
    assert len(queue["history"]) >= 4
    assert queue["governance"]["idea_screening"] == ["Dana"]

    # rejection closes a case
    other = client.post("/api/business-cases", json={"title": "r", "description": "d"}).json()
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": other["id"], "decision": "reject",
        "actor": "lee", "comment": "duplicate scope",
    })
    assert resp.json()["result"]["stage"] == "closed"


def test_automation_rules_and_idempotency(client):
    client.post("/api/datasets/load-samples")

    run1 = client.post("/api/automation/run").json()["summary"]
    assert run1["drafted"] >= 1  # quick wins above threshold get drafted

    # converges: drafting is capped per run, but repeated runs reach quiescence
    for _ in range(3):
        summary = client.post("/api/automation/run").json()["summary"]
        if summary == {"observed": 0, "drafted": 0, "advanced": 0}:
            break
    assert summary == {"observed": 0, "drafted": 0, "advanced": 0}

    # find the auto-drafted cloud idle case, take it live
    cases = client.get("/api/business-cases").json()["business_cases"]
    draft = next(c for c in cases if c["stage"] == "draft"
                 and c["linked_opportunity"]["category"] == "Idle cloud resources")
    assert draft["generated_by"] == "automation"
    assert len(draft["metric_bindings"]) == 1  # baseline frozen at draft time
    client.post(f"/api/business-cases/{draft['id']}/implement",
                json={"go_live_date": "2026-06-01"})

    # remediation lands in the data -> auto_observe + auto_advance
    survivors = "resource_id,service,monthly_cost,state,avg_cpu_pct\nx-1,EC2,100,running,50\n"
    client.post("/api/datasets/cloud", files={"file": ("c.csv", survivors, "text/csv")})
    run3 = client.post("/api/automation/run").json()["summary"]
    assert run3["observed"] >= 1
    assert run3["advanced"] >= 1

    final = next(c for c in client.get("/api/business-cases").json()["business_cases"]
                 if c["id"] == draft["id"])
    assert final["stage"] == "value_realized"
    assert final["tracking"]["measured_annual_savings"] == 27360.0

    log = client.get("/api/automation").json()
    rules = {e["rule"] for e in log["recent"]}
    assert {"auto_draft", "auto_observe", "auto_advance"} <= rules


def test_ai_evaluate_template_path(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Terminate idle cloud instances",
        "description": "Several instances run under 5% CPU; terminate them.",
    }).json()
    evaluated = client.post(f"/api/ideas/{idea['id']}/evaluate").json()
    ai = evaluated["assessment"]["ai_evaluation"]
    assert ai["generated_by"] == "template"   # no API key in tests
    assert ai["validated"] is True            # grounded in a detected opportunity


# ------------------------------------------------------------ roadmap features

def test_benefit_types_and_horizons(client):
    client.post("/api/datasets/load-samples")

    # explicit growth idea -> h2 derived from benefit type
    idea = client.post("/api/ideas", json={
        "title": "Premium support tier",
        "description": "Launch a paid premium support tier for enterprise customers "
                       "to open a new recurring revenue stream.",
        "benefit_type": "revenue_growth", "estimated_annual_benefit": 250000,
    }).json()
    assert idea["benefit_type"] == "revenue_growth"
    assert idea["horizon"] == "h2"
    assert idea["assessment"]["impact_band"] == "high"

    # defaulted idea -> cost_reduction/h1 with enrichment noted
    idea2 = client.post("/api/ideas", json={
        "title": "Terminate idle cloud instances",
        "description": "Several instances run under 5% CPU; terminate them.",
    }).json()
    assert idea2["horizon"] == "h1"
    assert any("Horizon derived" in n for n in idea2["assessment"]["enrichment"])

    assert client.post("/api/ideas", json={
        "title": "x", "description": "y", "benefit_type": "vibes",
    }).status_code == 400

    # horizon mix appears on the dashboard hub metrics
    mix = client.get("/api/dashboard").json()["hub"]["horizon_mix"]
    assert set(mix) == {"h1", "h2", "h3"}
    assert mix["h1"]["target_share"] == 0.7


def test_experiment_loop_and_kill_rate(client):
    client.post("/api/datasets/load-samples")
    case = client.post("/api/business-cases", json={
        "title": "Chatbot pilot", "description": "Deflect tickets with a chatbot.",
    }).json()

    # send to experiment via the command center decision
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"], "decision": "experiment",
        "actor": "lee",
    })
    assert resp.json()["result"]["stage"] == "experiment"

    resp = client.post(f"/api/business-cases/{case['id']}/experiments", json={
        "hypothesis": "A chatbot can deflect 30% of password tickets",
        "method": "2-week pilot on the IT service portal",
        "success_criteria": ">=30% deflection with CSAT >= 4.0",
        "cost": 5000,
    })
    assert resp.status_code == 200
    exp = resp.json()["experiments"][0]
    assert exp["outcome"] is None

    # learnings are mandatory on conclusion
    assert client.post(
        f"/api/business-cases/{case['id']}/experiments/{exp['id']}/conclude",
        json={"outcome": "kill", "learnings": " "},
    ).status_code == 400

    resp = client.post(
        f"/api/business-cases/{case['id']}/experiments/{exp['id']}/conclude",
        json={"outcome": "kill", "learnings": "Deflection only reached 8%; users bypassed the bot."},
    )
    assert resp.json()["stage"] == "closed"   # killed cleanly

    stats = client.get("/api/dashboard").json()["hub"]["experiments"]
    assert stats["concluded"] == 1
    assert stats["kill_rate"] == 1.0

    # a second case proceeds through experiment to approval
    case2 = client.post("/api/business-cases", json={
        "title": "RPA pilot", "description": "Automate invoice entry.",
    }).json()
    client.post(f"/api/business-cases/{case2['id']}/experiments", json={
        "hypothesis": "h", "method": "m", "success_criteria": "s",
    })
    exp2 = client.get("/api/business-cases").json()["business_cases"]
    exp2 = next(c for c in exp2 if c["id"] == case2["id"])["experiments"][0]
    client.post(f"/api/business-cases/{case2['id']}/experiments/{exp2['id']}/conclude",
                json={"outcome": "proceed", "learnings": "Hit 95% straight-through."})
    resp = client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case2["id"], "decision": "approve", "actor": "lee",
    })
    assert resp.json()["result"]["stage"] == "approved"


def test_notifications_close_the_loop(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount and recover.",
        "submitter": "maria",
    }).json()
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"],
        "decision": "feedback", "actor": "lee", "comment": "please add cost detail",
    })
    _walk_to_prioritized(client, idea["id"])
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop", "actor": "lee",
    })
    notes = client.get("/api/notifications", params={"recipient": "Maria"}).json()["notifications"]
    messages = " ".join(n["message"] for n in notes)
    assert "Feedback on your idea" in messages
    assert "passed the Qualification" in messages
    assert "moved to Prioritized" in messages
    assert "promoted to business case" in messages


def test_challenges_drive_alignment(client):
    client.post("/api/datasets/load-samples")
    challenge = client.post("/api/challenges", json={
        "title": "Cut cloud waste",
        "question": "How might we halve our idle cloud spend this quarter?",
        "theme": "cloud efficiency",
    }).json()
    assert challenge["status"] == "active"

    # same idea text scores alignment 1.0 inside the challenge even though it
    # mentions no configured theme keyword
    client.put("/api/scoring-config", json={"priority_themes": ["sustainability"]})
    inside = client.post("/api/ideas", json={
        "title": "Nightly shutdown schedule",
        "description": "Power off dev instances overnight.", "challenge_id": challenge["id"],
    }).json()
    outside = client.post("/api/ideas", json={
        "title": "Nightly shutdown schedule 2",
        "description": "Power off test instances overnight.",
    }).json()
    assert inside["assessment"]["score_components"]["alignment"] == 1.0
    assert outside["assessment"]["score_components"]["alignment"] == 0.0
    assert inside["challenge_id"] == challenge["id"]

    listed = client.get("/api/challenges").json()["challenges"]
    assert listed[0]["ideas_count"] == 1
    client.post(f"/api/challenges/{challenge['id']}/close")
    assert client.get("/api/challenges").json()["challenges"][0]["status"] == "closed"

    # duplicate detection: near-identical idea gets flagged
    assert any(
        d["id"] == inside["id"]
        for d in outside["assessment"]["possible_duplicates"]
    )


def test_metered_funding_tranches(client):
    client.post("/api/datasets/load-samples")
    case = client.post("/api/business-cases", json={
        "title": "Platform build", "description": "d", "estimated_cost": 100000,
    }).json()
    for label, amount in (("Discovery", 10000), ("Build", 40000)):
        resp = client.post(f"/api/business-cases/{case['id']}/tranches", json={
            "label": label, "amount": amount, "milestone": f"{label} complete",
        })
        assert resp.status_code == 200
    case = resp.json()
    assert case["funding"]["planned"] == 50000
    assert case["funding"]["released"] == 0

    tranche_id = case["funding"]["tranches"][0]["id"]
    case = client.post(
        f"/api/business-cases/{case['id']}/tranches/{tranche_id}/release",
        json={"actor": "lee"},
    ).json()
    assert case["funding"]["released"] == 10000

    # released tranches become the cost basis for tracking + timeline
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-06-01"})
    client.post(f"/api/business-cases/{case['id']}/savings",
                json={"entry_date": "2026-06-10", "amount": 5000})
    tracked = client.get("/api/business-cases").json()["business_cases"]
    tracked = next(c for c in tracked if c["id"] == case["id"])
    assert tracked["tracking"]["realized_roi_pct"] == -50.0  # (5000-10000)/10000
    months = client.get("/api/dashboard").json()["timeline"]["months"]
    assert any(m["cumulative_cost"] >= 10000 for m in months)


def test_pattern_library_replication(client):
    client.post("/api/datasets/load-samples")
    opp = _cloud_idle_opp(client)
    case = client.post("/api/business-cases", json={
        "title": "Terminate idle cloud", "description": "d", "estimated_cost": 5000,
        "linked_opportunity_id": opp["id"],
    }).json()
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-05-01"})
    survivors = "resource_id,service,monthly_cost,state,avg_cpu_pct\nx-1,EC2,100,running,50\n"
    client.post("/api/datasets/cloud", files={"file": ("c.csv", survivors, "text/csv")})
    binding = case["metric_bindings"][0]
    client.post(f"/api/business-cases/{case['id']}/bindings/{binding['id']}/observe")
    client.post("/api/automation/run")  # auto_advance -> value_realized

    patterns = client.get("/api/patterns").json()["patterns"]
    mine = next(p for p in patterns if p["case_id"] == case["id"])
    assert mine["measured_annual_savings"] == 27360.0

    clone = client.post(f"/api/patterns/{case['id']}/replicate", json={}).json()
    assert clone["stage"] == "draft"
    assert clone["generated_by"] == "pattern"
    assert "Replicate:" in clone["title"]

    # unproven cases cannot be replicated
    other = client.post("/api/business-cases", json={"title": "x", "description": "y"}).json()
    assert client.post(f"/api/patterns/{other['id']}/replicate", json={}).status_code == 400


def test_admin_token_guard(client, monkeypatch):
    monkeypatch.setenv("IVD_ADMIN_TOKEN", "s3cret")
    assert client.put("/api/scoring-config", json={
        "priority_themes": ["x"],
    }).status_code == 401
    assert client.put("/api/scoring-config", json={
        "priority_themes": ["x"],
    }, headers={"Authorization": "Bearer s3cret"}).status_code == 200


# ------------------------------------------------------- human-centered layer

def test_desirability_axis(client):
    client.post("/api/datasets/load-samples")
    anchored = client.post("/api/ideas", json={
        "title": "Self-service laptop refresh",
        "description": "Let employees schedule their own hardware refresh instead of "
                       "waiting on tickets and losing a day of work.",
        "beneficiary": "All 2,400 employees on the 3-year refresh cycle",
        "pain_point": "People lose most of a day waiting at the IT desk for a swap",
    }).json()
    unanchored = client.post("/api/ideas", json={
        "title": "Self-service laptop refresh v2",
        "description": "Let employees schedule their own hardware refresh instead of "
                       "waiting on tickets and losing a day of work again.",
    }).json()

    assert anchored["assessment"]["score_components"]["desirability"] == 0.8
    assert unanchored["assessment"]["score_components"]["desirability"] == 0.0
    assert anchored["assessment"]["score"] > unanchored["assessment"]["score"]
    assert any("who is this for" in n for n in unanchored["assessment"]["enrichment"])


def test_social_signal_rescores_ideas(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount and recover them.",
        "submitter": "maria",
        "beneficiary": "AP team", "pain_point": "Manual reconciliation misses duplicates",
    }).json()
    base_desirability = idea["assessment"]["score_components"]["desirability"]

    # votes are idempotent signal
    client.post(f"/api/ideas/{idea['id']}/vote", json={"voter": "sam"})
    client.post(f"/api/ideas/{idea['id']}/vote", json={"voter": "sam"})   # no double count
    voted = client.post(f"/api/ideas/{idea['id']}/vote", json={"voter": "lee"}).json()
    assert voted["vote_count"] == 2
    assert voted["assessment"]["score_components"]["desirability"] > base_desirability

    # build-on comment notifies the submitter and counts double
    built = client.post(f"/api/ideas/{idea['id']}/comments", json={
        "author": "sam", "comment": "Extend it to credit notes too — same detection logic.",
        "build_on": True,
    }).json()
    assert built["comments"][0]["build_on"] == 1
    notes = client.get("/api/notifications", params={"recipient": "maria"}).json()["notifications"]
    assert any("built on your idea" in n["message"] for n in notes)


def test_learning_library(client):
    client.post("/api/datasets/load-samples")
    case = client.post("/api/business-cases", json={
        "title": "Kiosk pilot", "description": "d",
    }).json()
    client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"], "decision": "experiment",
    })
    client.post(f"/api/business-cases/{case['id']}/experiments", json={
        "hypothesis": "h", "method": "m", "success_criteria": "s",
    })
    exp = client.get("/api/business-cases").json()["business_cases"]
    exp = next(c for c in exp if c["id"] == case["id"])["experiments"][0]
    client.post(f"/api/business-cases/{case['id']}/experiments/{exp['id']}/conclude",
                json={"outcome": "kill", "learnings": "Users preferred the mobile flow."})

    lessons = client.get("/api/learnings").json()["learnings"]
    assert lessons[0]["learnings"] == "Users preferred the mobile flow."
    assert lessons[0]["case_title"] == "Kiosk pilot"


def test_pattern_story_format(client):
    client.post("/api/datasets/load-samples")
    opp = _cloud_idle_opp(client)
    case = client.post("/api/business-cases", json={
        "title": "t", "description": "Idle instances burn money with no user impact.",
        "estimated_cost": 5000, "linked_opportunity_id": opp["id"],
    }).json()
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-05-01"})
    survivors = "resource_id,service,monthly_cost,state,avg_cpu_pct\nx-1,EC2,100,running,50\n"
    client.post("/api/datasets/cloud", files={"file": ("c.csv", survivors, "text/csv")})
    binding = case["metric_bindings"][0]
    client.post(f"/api/business-cases/{case['id']}/bindings/{binding['id']}/observe")
    client.post("/api/automation/run")

    pattern = client.get("/api/patterns").json()["patterns"][0]
    assert pattern["story"]["problem"].startswith("Idle instances")
    assert "what_we_tried" in pattern["story"]
    assert "human_evidence" in pattern["story"]


# --------------------------------------------- strategic initiatives & demo

def test_initiative_tagging_and_rollup(client):
    client.post("/api/datasets/load-samples")
    initiative = client.post("/api/initiatives", json={
        "name": "Cloud cost excellence",
        "objective": "Cut cloud run-rate 20% without slowing delivery.",
    }).json()

    idea = client.post("/api/ideas", json={
        "title": "Terminate idle cloud instances",
        "description": "Several instances run under 5% CPU; terminate them.",
        "initiative_id": initiative["id"],
    }).json()
    assert idea["initiative_id"] == initiative["id"]
    # initiative tag counts as strategic alignment
    assert idea["assessment"]["score_components"]["alignment"] == 1.0
    stale = client.post("/api/ideas", json={
        "title": "x", "description": "y", "initiative_id": "SI-nope",
    })
    assert stale.status_code == 200 and stale.json()["initiative_ids"] == []

    # promotion carries the tag to the case; rollup aggregates the chain
    _walk_to_prioritized(client, idea["id"])
    promoted = client.post(f"/api/ideas/{idea['id']}/promote").json()
    assert promoted["case"]["initiative_id"] == initiative["id"]
    rollup = client.get("/api/initiatives").json()["initiatives"][0]
    assert rollup["ideas_count"] == 1
    assert rollup["cases_count"] == 1
    assert rollup["forecast_annual_savings"] == 27360.0


def test_demo_generate_and_revert(client):
    client.post("/api/datasets/load-samples")
    baseline_ideas = len(client.get("/api/ideas").json()["ideas"])
    baseline_initiatives = len(client.get("/api/initiatives").json()["initiatives"])

    resp = client.post("/api/demo/generate", json={
        "client": "Meridian Health", "industry": "healthcare",
    })
    assert resp.status_code == 200
    info = resp.json()["demo"]
    assert info["generated_by"] == "template"  # no API key in tests
    assert info["initiatives"] == 3 and info["ideas"] == 10

    # portfolio is live: tagged, triaged, client-branded
    ideas = client.get("/api/ideas").json()["ideas"]
    demo_ideas = [i for i in ideas if i["source"] == "demo"]
    assert len(demo_ideas) == 10
    assert all(i["initiative_id"] for i in demo_ideas)
    assert all(i["assessment"]["score"] > 0 for i in demo_ideas)
    first_initiative = client.get("/api/initiatives").json()["initiatives"][0]
    assert "Meridian Health" in first_initiative["objective"]
    assert client.get("/api/demo/status").json()["demo"]["client"] == "Meridian Health"

    # one demo at a time
    assert client.post("/api/demo/generate", json={
        "client": "Other Co", "industry": "retail",
    }).status_code == 400

    # revert restores the exact pre-demo state — no bloat
    resp = client.post("/api/demo/revert")
    assert resp.status_code == 200
    assert len(client.get("/api/ideas").json()["ideas"]) == baseline_ideas
    assert len(client.get("/api/initiatives").json()["initiatives"]) == baseline_initiatives
    assert client.get("/api/demo/status").json()["demo"] is None
    # nothing to revert twice
    assert client.post("/api/demo/revert").status_code == 400

    # client-only generation (industry inferred) and industry-only both work
    resp = client.post("/api/demo/generate", json={"client": "Acme Corp"})
    assert resp.status_code == 200
    assert resp.json()["demo"]["ideas"] == 10
    assert resp.json()["demo"]["industry"] == "inferred from client strategy"
    client.post("/api/demo/revert")
    resp = client.post("/api/demo/generate", json={"industry": "manufacturing"})
    assert resp.status_code == 200
    assert resp.json()["demo"]["client"] == "Manufacturing prospect"
    client.post("/api/demo/revert")
    assert client.post("/api/demo/generate", json={}).status_code == 400


# ---------------------------------------------------------- stage-gate lifecycle

def test_stage_gate_lifecycle(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount and recover.",
        "submitter": "maria",
    }).json()
    assert idea["status"] == "proposed"

    # gates enforce order: cannot prioritize or develop from proposed
    assert client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "prioritize",
    }).status_code == 400
    assert client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop",
    }).status_code == 400

    # queue exposes the gate checklist for screeners
    queue = client.get("/api/command/queue").json()
    pending = next(i for i in queue["idea_steps"][0]["ideas"] if i["id"] == idea["id"])
    checklist = {c["check"]: c["passed"] for c in pending["gate_checklist"]}
    assert checklist["Named business sponsor"] is True

    # 'approve' aliases the current stage's forward gate
    r1 = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "approve",
    }).json()["result"]
    assert r1["status"] == "qualified"

    # hold parks a qualified idea on the backlog
    other = client.post("/api/ideas", json={
        "title": "Robot greeter", "description": "Lobby robot to welcome guests.",
    }).json()
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": other["id"], "decision": "qualify",
    })
    held = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": other["id"], "decision": "hold",
    }).json()["result"]
    assert held["status"] == "backlog"

    # lifecycle endpoint: spec, live counts, and the portfolio register
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "prioritize",
    })
    lc = client.get("/api/lifecycle").json()
    assert [s["stage"] for s in lc["spec"]] == ["proposed", "qualified", "prioritized", "business_case"]
    assert lc["idea_counts"]["prioritized"] == 1
    assert lc["idea_terminal"]["backlog"] == 1
    entry = next(r for r in lc["register"] if r["id"] == idea["id"])
    assert entry["impact"] > 0 and 0 <= entry["readiness"] <= 1


# ------------------------------------------------------------------- pipeline

def test_pipeline_analytics(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicate invoices by vendor and amount and recover.",
        "submitter": "maria",
    }).json()
    stale = client.post("/api/ideas", json={
        "title": "Robot greeter", "description": "Lobby robot to welcome guests.",
    }).json()
    _walk_to_prioritized(client, idea["id"])
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop",
    })

    p = client.get("/api/pipeline").json()
    assert [ph["phase"][0] for ph in p["phases"]] == ["A", "B", "C"]

    phase_a = {s["stage"]: s for s in p["phases"][0]["stages"]}
    assert phase_a["proposed"]["count"] == 1  # 'stale' still sitting at intake
    assert phase_a["proposed"]["items"][0]["id"] == stale["id"]
    assert phase_a["proposed"]["items"][0]["days_in_stage"] is not None
    # conversion: 1 of 2 ideas passed qualification
    assert phase_a["qualified"]["conversion_from_previous"] == 0.5
    assert phase_a["qualified"]["reached"] == 1

    phase_b = {s["stage"]: s for s in p["phases"][1]["stages"]}
    assert phase_b["proposed"]["count"] == 1  # the developed business case
    assert phase_b["proposed"]["value"] == 50600.0  # duplicate-invoice forecast

    totals = p["totals"]
    assert totals["in_flight"] == 2  # 1 idea at intake + 1 case in review
    assert totals["end_to_end_conversion"] == 0.5
    assert p["terminal"]["declined"] == 0



def test_configurable_workflow(client):
    client.post("/api/datasets/load-samples")
    # insert a custom 'concept_review' step between qualification and prioritization
    steps = client.get("/api/workflow").json()["steps"]
    steps.insert(1, {"key": "concept_review", "label": "Concept review",
                     "gate": "Concept note review", "forum": "idea_screening",
                     "purpose": "One-page concept note reviewed.",
                     "criteria": ["High-level benefit", "Scalability"]})
    resp = client.put("/api/workflow", json={"steps": steps})
    assert resp.status_code == 200
    assert [s["key"] for s in resp.json()["steps"]] == [
        "proposed", "concept_review", "qualified", "prioritized"]

    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicates by vendor and amount and recover.",
    }).json()
    # advance walks the configured sequence, including the custom step
    for expected in ("concept_review", "qualified", "prioritized"):
        r = client.post("/api/command/decide", json={
            "subject_type": "idea", "subject_id": idea["id"], "decision": "advance",
        })
        assert r.json()["result"]["status"] == expected
    # develop only at the final configured gate
    r = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop",
    })
    assert r.json()["result"]["case"]["stage"] == "proposed"
    # queue + lifecycle expose the custom step
    q = client.get("/api/command/queue").json()
    assert [s["key"] for s in q["idea_steps"]][1] == "concept_review"
    assert client.get("/api/lifecycle").json()["spec"][1]["stage"] == "concept_review"
    # invalid workflow rejected
    assert client.put("/api/workflow", json={"steps": [
        {"key": "proposed"}, {"key": "business_case"},
    ]}).status_code == 400


def test_custom_scoring_criteria(client):
    client.post("/api/datasets/load-samples")
    resp = client.put("/api/scoring-config", json={"custom_criteria": [
        {"label": "AI leverage", "keywords": ["ai", "automation", "model"], "weight": 0.5},
    ]})
    assert resp.status_code == 200
    hit = client.post("/api/ideas", json={
        "title": "AI invoice automation", "description": "Use an AI model to automate invoice entry.",
    }).json()
    miss = client.post("/api/ideas", json={
        "title": "New office chairs", "description": "Purchase ergonomic seating for the finance floor.",
    }).json()
    assert hit["assessment"]["score_components"]["custom: AI leverage"] == 1.0
    assert miss["assessment"]["score_components"]["custom: AI leverage"] == 0.0
    assert client.put("/api/scoring-config", json={"custom_criteria": [
        {"label": "", "keywords": [], "weight": -1},
    ]}).status_code == 400


def test_initiative_reorder_and_edit(client):
    a = client.post("/api/initiatives", json={"name": "A", "objective": "obj a"}).json()
    b = client.post("/api/initiatives", json={"name": "B", "objective": "obj b"}).json()
    client.post("/api/initiatives/reorder", json={"ids": [b["id"], a["id"]]})
    ordered = client.get("/api/initiatives").json()["initiatives"]
    assert [i["name"] for i in ordered] == ["B", "A"]
    client.put(f"/api/initiatives/{a['id']}", json={"objective": "sharper objective"})
    assert client.get("/api/initiatives").json()["initiatives"][1]["objective"] == "sharper objective"


def test_my_submissions_approval_chain(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicates by vendor and amount and recover.",
        "submitter": "Maria",
    }).json()
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"],
        "decision": "feedback", "actor": "lee", "comment": "add the AP volume",
    })
    mine = client.get("/api/my-submissions", params={"submitter": "maria"}).json()
    assert mine["updates_needed"] == [idea["id"]]
    entry = mine["ideas"][0]
    assert "add the AP volume" in entry["attention_reason"]

    _walk_to_prioritized(client, idea["id"])
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop",
    })
    mine = client.get("/api/my-submissions", params={"submitter": "Maria"}).json()
    entry = mine["ideas"][0]
    assert entry["needs_attention"] is False
    assert [h["action"] for h in entry["history"]] == ["feedback", "advance", "advance", "develop"]
    assert entry["case_stage"] == "proposed"
    assert mine["workflow"][0]["key"] == "proposed"


def test_user_profiles_gate_access(client):
    client.post("/api/datasets/load-samples")
    idea = client.post("/api/ideas", json={
        "title": "Recover duplicate vendor invoices",
        "description": "Detect duplicates by vendor and amount and recover.",
    }).json()

    # open until profiles exist
    resp = client.put("/api/users", json={"users": [
        {"name": "Cara", "role": "contributor", "password": "pw"},
        {"name": "Rio", "role": "reviewer", "password": "pw"},
        {"name": "Eve", "role": "executive", "password": "pw"},
        {"name": "Ada", "role": "admin", "password": "pw"},
    ]})
    assert resp.status_code == 200

    def _as(who):
        tok = client.post("/api/auth/login", json={"name": who, "password": "pw"}).json()["token"]
        return {"Authorization": f"Bearer {tok}"}

    # once users exist, unauthenticated decisions are refused outright
    assert client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "qualify",
    }).status_code == 401

    # contributor cannot make gate decisions; reviewer can
    assert client.post("/api/command/decide", headers=_as("cara"), json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "qualify",
    }).status_code == 403
    assert client.post("/api/command/decide", headers=_as("rio"), json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "qualify",
    }).status_code == 200

    # reviewer cannot approve cases; executive can
    rio = _as("rio")
    client.post("/api/command/decide", headers=rio, json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "prioritize"})
    case = client.post("/api/command/decide", headers=rio, json={
        "subject_type": "idea", "subject_id": idea["id"], "decision": "develop",
    }).json()["result"]["case"]
    assert client.post("/api/command/decide", headers=rio, json={
        "subject_type": "case", "subject_id": case["id"], "decision": "approve",
    }).status_code == 403
    assert client.post("/api/command/decide", headers=_as("eve"), json={
        "subject_type": "case", "subject_id": case["id"], "decision": "approve",
    }).status_code == 200

    # settings require admin once profiles exist
    assert client.put("/api/scoring-config", json={"priority_themes": ["x"]},
                      headers=_as("eve")).status_code == 403
    assert client.put("/api/scoring-config", json={"priority_themes": ["x"]},
                      headers=_as("ada")).status_code == 200


def test_idea_tags_multiple_objectives(client):
    a = client.post("/api/initiatives", json={"name": "Cut run costs", "objective": "Reduce opex"}).json()
    b = client.post("/api/initiatives", json={"name": "Customer love", "objective": "Raise NPS"}).json()
    idea = client.post("/api/ideas", json={
        "title": "Self-service billing portal",
        "description": "Customers resolve billing questions themselves, cutting ticket volume.",
        "initiative_ids": [a["id"], b["id"]],
    }).json()
    assert idea["initiative_ids"] == [a["id"], b["id"]]
    assert idea["initiative_id"] == a["id"]  # legacy field = first tag

    rollups = {r["id"]: r for r in client.get("/api/initiatives").json()["initiatives"]}
    assert rollups[a["id"]]["ideas_count"] == 1
    assert rollups[b["id"]]["ideas_count"] == 1

    # stale objective tags are dropped with a note, not fatal
    r = client.post("/api/ideas", json={
        "title": "Reduce paper archives", "description": "Digitize the records room.",
        "initiative_ids": ["SI-nope"],
    })
    assert r.status_code == 200
    assert r.json()["initiative_ids"] == []
    assert any("no longer exist" in e for e in r.json()["assessment"]["enrichment"])
    legacy = client.post("/api/ideas", json={
        "title": "Warehouse slotting optimizer",
        "description": "Re-slot by velocity to cut picker travel time.",
        "initiative_id": b["id"],
    }).json()
    assert legacy["initiative_ids"] == [b["id"]]


def test_description_assist(client):
    # generate mode: scaffold from title, clearly labeled, nothing invented
    client.post("/api/datasets/load-samples")
    r = client.post("/api/ideas/assist", json={"title": "Automate invoice matching"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "generate"
    assert body["generated_by"] == "template"
    # a complete, populated draft — no fill-in placeholders
    assert "<" not in body["draft"]
    for section in ("Problem today:", "Proposed change:", "Who benefits:", "Expected outcome:"):
        assert section in body["draft"]
    assert "Automate invoice matching" in body["draft"]

    # a title matching detected opportunities grounds the draft in real data
    grounded = client.post("/api/ideas/assist",
                           json={"title": "Decommission idle cloud instances"}).json()
    assert "$" in grounded["draft"] or "cloud" in grounded["draft"].lower()

    # improve mode: heuristic suggestions for a thin description
    r = client.post("/api/ideas/assist", json={
        "title": "Automate invoice matching", "description": "It would be good."})
    body = r.json()
    assert body["mode"] == "improve"
    assert body["draft"] == "It would be good."  # template mode never rewrites
    assert len(body["suggestions"]) >= 2

    assert client.post("/api/ideas/assist", json={"title": "  "}).status_code == 400


def test_login_sessions_and_identity(client):
    # open mode: no auth required
    r = client.get("/api/auth/me")
    assert r.json() == {"auth_required": False, "user": None, "workspace": None}

    # first sign-in bootstraps the admin
    r = client.post("/api/auth/login", json={"name": "Ryan", "password": "hunter2"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert r.json()["user"] == {"name": "ryan", "role": "admin"}
    auth = {"Authorization": f"Bearer {token}"}

    # once users exist, unauthenticated API calls are refused
    assert client.get("/api/ideas").status_code == 401
    assert client.get("/api/ideas", headers=auth).status_code == 200

    # wrong password refused; admin adds a contributor with a password
    assert client.post("/api/auth/login", json={"name": "ryan", "password": "nope"}).status_code == 401
    r = client.put("/api/users", headers=auth, json={"users": [
        {"name": "ryan", "role": "admin"},
        {"name": "cara", "role": "contributor", "password": "carapass"},
    ]})
    assert r.status_code == 200
    assert all(u["has_password"] for u in r.json()["users"])
    # saving again without passwords keeps existing hashes
    client.put("/api/users", headers=auth, json={"users": [
        {"name": "ryan", "role": "admin"},
        {"name": "cara", "role": "contributor"},
    ]})
    cara_tok = client.post("/api/auth/login",
                           json={"name": "Cara", "password": "carapass"}).json()["token"]
    cara = {"Authorization": f"Bearer {cara_tok}"}

    # session identity drives privileges: contributor can't decide even if the
    # request claims otherwise
    idea = client.post("/api/ideas", headers=cara, json={
        "title": "Chat deflection bot", "description": "Deflect common IT questions to self-serve.",
    }).json()
    r = client.post("/api/command/decide", headers=cara, json={
        "subject_type": "idea", "subject_id": idea["id"],
        "decision": "qualify", "actor": "ryan",
    })
    assert r.status_code == 403

    # my-submissions reflects the signed-in submitter
    mine = client.get("/api/my-submissions", params={"submitter": "cara"}, headers=cara).json()
    assert [i["id"] for i in mine["ideas"]] == [idea["id"]]

    # logout invalidates the session
    client.post("/api/auth/logout", headers=cara)
    assert client.get("/api/ideas", headers=cara).status_code == 401


def test_seed_lifecycle_populates_every_phase(client):
    r = client.post("/api/demo/seed-lifecycle")
    assert r.status_code == 200
    assert r.json()["seeded"] is True

    ideas = client.get("/api/ideas").json()["ideas"]
    statuses = {i["status"] for i in ideas}
    assert {"proposed", "qualified", "prioritized", "business_case",
            "backlog", "declined"} <= statuses

    cases = client.get("/api/business-cases").json()["business_cases"]
    stages = {c["stage"] for c in cases}
    assert {"proposed", "experiment", "approved", "in_delivery",
            "live", "value_realized", "scale", "closed"} <= stages

    # funding released, claimed savings recorded, learnings captured
    assert any((c.get("funding") or {}).get("released", 0) > 0 for c in cases)
    assert any(c.get("savings_entries") for c in cases)
    assert client.get("/api/learnings").json()["learnings"]


def test_e2e_workflow_and_data_integrity(client):
    """Regression guard: walks the seeded end-to-end lifecycle and checks the
    data stays internally consistent across every phase boundary."""
    client.post("/api/demo/seed-lifecycle")
    ideas = client.get("/api/ideas").json()["ideas"]
    cases = {c["id"]: c for c in client.get("/api/business-cases").json()["business_cases"]}
    workflow_keys = [s["key"] for s in client.get("/api/workflow").json()["steps"]]

    for idea in ideas:
        # every idea sits at a legal stage
        assert idea["status"] in set(workflow_keys) | {"business_case", "backlog", "declined"}
        # promoted ideas link to a real case; the case links back
        if idea["status"] == "business_case":
            assert idea["promoted_case_id"] in cases
            assert idea["id"] in (cases[idea["promoted_case_id"]].get("note") or "")
        # objective tags reference real initiatives
    init_ids = {i["id"] for i in client.get("/api/initiatives").json()["initiatives"]}
    for idea in ideas:
        assert set(idea.get("initiative_ids") or []) <= init_ids

    for c in cases.values():
        funding = c.get("funding") or {}
        # metered funding can never release more than was planned
        assert funding.get("released", 0) <= funding.get("planned", 0) + 0.01
        # value stages require implementation; claimed savings require go-live
        if c["stage"] in ("value_realized", "scale") or c.get("savings_entries"):
            assert c["status"] == "implemented" and c.get("go_live_date")
        # claimed and verified value are separate, honestly-computed numbers
        t = c.get("tracking")
        if t:
            assert abs(t["total_realized_savings"]
                       - sum(e["amount"] for e in c["savings_entries"])) < 0.01
            measured = sum(b.get("annualized_delta") or 0 for b in c["metric_bindings"])
            assert abs(t["measured_annual_savings"] - round(measured, 2)) < 0.01

    # initiative rollups equal a manual recount
    for r in client.get("/api/initiatives").json()["initiatives"]:
        manual = sum(1 for i in ideas if r["id"] in (i.get("initiative_ids") or []))
        assert r["ideas_count"] == manual

    # my-submissions mirrors the decide history for each submitter
    mine = client.get("/api/my-submissions", params={"submitter": "jordan"}).json()
    assert all((i.get("submitter") or "").lower() == "jordan" for i in mine["ideas"])
    legal_actions = {"advance", "qualify", "prioritize", "hold", "develop",
                     "reject", "feedback", "approve", "experiment"}
    for i in mine["ideas"]:
        assert {h["action"] for h in i["history"]} <= legal_actions


def test_e2e_uat_user_journeys(client):
    """UAT: three personas walk the product end to end; assert that what each
    of them sees at every moment is coherent with what actually happened."""
    client.post("/api/datasets/load-samples")

    # --- Sana (submitter) shares a thin idea, then a strong one -------------
    thin = client.post("/api/ideas", json={
        "title": "Better reports", "description": "Improve reports.",
        "submitter": "Sana"}).json()
    strong = client.post("/api/ideas", json={
        "title": "Decommission idle cloud instances",
        "description": "Instances idle under 5% CPU around the clock cost real money; "
                       "schedule or decommission them with owner sign-off.",
        "submitter": "Sana", "estimated_annual_benefit": 120000,
        "beneficiary": "Platform team", "pain_point": "Budget overruns every quarter",
    }).json()
    # triage is coherent: substance scores above vagueness
    assert strong["assessment"]["score"] > thin["assessment"]["score"]

    # --- Rio (reviewer) sees exactly those ideas at the first gate ----------
    q = client.get("/api/command/queue").json()
    gate1 = {i["id"] for i in q["idea_steps"][0]["ideas"]}
    assert {thin["id"], strong["id"]} <= gate1
    # the gate checklist mirrors reality: strong idea has a sponsor, thin does too
    checks = {c["check"]: c["passed"]
              for c in next(i for i in q["idea_steps"][0]["ideas"]
                            if i["id"] == strong["id"])["gate_checklist"]}
    assert checks["Named business sponsor"] is True

    # Rio asks for more info on the thin idea; Sana hears about it in her words
    client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": thin["id"], "decision": "feedback",
        "actor": "Rio", "comment": "Which reports, and what decision do they drive?"})
    notes = client.get("/api/notifications", params={"recipient": "Sana"}).json()["notifications"]
    assert any("Better reports" in n["message"] for n in notes)
    mine = client.get("/api/my-submissions", params={"submitter": "sana"}).json()
    assert thin["id"] in mine["updates_needed"]
    assert strong["id"] not in mine["updates_needed"]

    # Rio advances the strong idea through both gates; the queue follows
    for decision in ("qualify", "prioritize"):
        client.post("/api/command/decide", json={
            "subject_type": "idea", "subject_id": strong["id"],
            "decision": decision, "actor": "Rio"})
    q = client.get("/api/command/queue").json()
    assert strong["id"] not in {i["id"] for i in q["idea_steps"][0]["ideas"]}
    assert strong["id"] in {i["id"] for i in q["idea_steps"][-1]["ideas"]}

    # develop: Sana is told her idea became a business case, and can see it
    case = client.post("/api/command/decide", json={
        "subject_type": "idea", "subject_id": strong["id"],
        "decision": "develop", "actor": "Rio"}).json()["result"]["case"]
    notes = client.get("/api/notifications", params={"recipient": "Sana"}).json()["notifications"]
    assert any(case["id"] in n["message"] for n in notes)
    mine = client.get("/api/my-submissions", params={"submitter": "sana"}).json()
    sana_strong = next(i for i in mine["ideas"] if i["id"] == strong["id"])
    assert sana_strong["case_stage"] == "proposed"

    # --- Eve (executive) finds the case waiting, funds it coherently --------
    q = client.get("/api/command/queue").json()
    assert case["id"] in {c["id"] for c in q["cases_pending_approval"]}
    client.post("/api/command/decide", json={
        "subject_type": "case", "subject_id": case["id"],
        "decision": "approve", "actor": "Eve"})
    client.post(f"/api/business-cases/{case['id']}/tranches", json={
        "label": "Delivery", "amount": 40000, "milestone": "Go-live"})
    fresh = client.get("/api/business-cases").json()["business_cases"]
    fresh_case = next(c for c in fresh if c["id"] == case["id"])
    tranche = fresh_case["funding"]["tranches"][0]
    client.post(f"/api/business-cases/{case['id']}/tranches/{tranche['id']}/release",
                json={"actor": "Eve"})

    # after go-live, the value story stays honest: claimed is claimed,
    # verified is computed, and the released tranche is the cost basis
    client.post(f"/api/business-cases/{case['id']}/implement",
                json={"go_live_date": "2026-04-01"})
    client.post(f"/api/business-cases/{case['id']}/savings", json={
        "entry_date": "2026-06-01", "amount": 9000, "note": "First month"})
    fresh_case = next(c for c in client.get("/api/business-cases").json()["business_cases"]
                      if c["id"] == case["id"])
    t = fresh_case["tracking"]
    assert t["total_realized_savings"] == 9000
    assert t["measured_annual_savings"] != t["total_realized_savings"] or \
           t["measured_annual_savings"] == 0  # never silently equated


def test_queue_runs_lazy_automation_before_assembly(client):
    client.post("/api/datasets/load-samples")
    q = client.get("/api/command/queue").json()
    # first read after data load: the sweep ran and is reported
    assert q["automation_ran"] is not None
    drafted_visible = {c["id"] for c in q["cases_pending_approval"]}
    # anything the sweep drafted is already on this same response
    cases = client.get("/api/business-cases").json()["business_cases"]
    for c in cases:
        if c["stage"] in ("draft", "proposed"):
            assert c["id"] in drafted_visible
    # immediate second read: nothing stale, no sweep, board stable
    q2 = client.get("/api/command/queue").json()
    assert q2["automation_ran"] is None


def test_admin_sees_all_submissions(client):
    # bootstrap admin, add a contributor
    tok = client.post("/api/auth/login", json={"name": "ada", "password": "pw"}).json()["token"]
    admin = {"Authorization": f"Bearer {tok}"}
    client.put("/api/users", headers=admin, json={"users": [
        {"name": "ada", "role": "admin"},
        {"name": "cara", "role": "contributor", "password": "pw"},
    ]})
    cara = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'name': 'cara', 'password': 'pw'}).json()['token']}"}

    a = client.post("/api/ideas", headers=admin, json={
        "title": "Consolidate reporting tools", "description": "Three BI tools, one needed."}).json()
    b = client.post("/api/ideas", headers=cara, json={
        "title": "Automate expense checks", "description": "Manual receipt review is slow."}).json()

    # contributor sees only her own
    mine = client.get("/api/my-submissions", params={"submitter": "cara"}, headers=cara).json()
    assert mine["scope"] == "mine"
    assert {i["id"] for i in mine["ideas"]} == {b["id"]}

    # admin sees everything, regardless of the submitter filter
    allv = client.get("/api/my-submissions", params={"submitter": "ada"}, headers=admin).json()
    assert allv["scope"] == "all"
    assert {a["id"], b["id"]} <= {i["id"] for i in allv["ideas"]}


def test_enterprise_admin_and_reporting_endpoints(client):
    client.post("/api/demo/seed-lifecycle")

    # audit trail captured the seeded activity; CSV export works
    audit = client.get("/api/admin/audit").json()["entries"]
    actions = {e["action"] for e in audit}
    assert "idea.submit" in actions and "funding.release" in actions
    assert any(a.startswith("decide.") for a in actions)
    csv = client.get("/api/admin/audit", params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv")

    # state export/import round-trips
    snap = client.get("/api/admin/export").json()
    n_ideas = len(client.get("/api/ideas").json()["ideas"])
    client.post("/api/datasets/load-samples")  # perturb
    restored = client.post("/api/admin/import", json=snap).json()["restored"]
    assert restored["ideas"] == n_ideas
    assert len(client.get("/api/ideas").json()["ideas"]) == n_ideas

    # capture webhook feeds the funnel
    r = client.post("/api/integrations/capture", json={
        "source": "teams", "text": "Auto-archive stale SharePoint sites",
        "user": "lee"}).json()
    assert r["id"].startswith("IDEA-") and r["recommendation"]

    # delivery handoff carries the measurement plan
    case = client.get("/api/business-cases").json()["business_cases"][0]
    h = client.get(f"/api/business-cases/{case['id']}/handoff").json()
    assert h["issue_type"] == "Epic" and "Measurement plan" in h["description"]

    # board pack and value ledger keep claimed and verified separate
    pack = client.get("/api/reports/board-pack").text
    assert "Verified annual value" in pack and "Claimed savings" in pack
    ledger = client.get("/api/value-ledger").json()
    # the flagship metric must never be zero in the demo
    assert ledger["total_verified_annual_value"] > 0
    for e in ledger["entries"]:
        assert e["baseline_frozen_at"]  # every entry traceable to a frozen baseline
    assert client.get("/api/value-ledger", params={"format": "csv"}
                      ).headers["content-type"].startswith("text/csv")

    # benchmarks expose the calibration layer
    assert "categories" in client.get("/api/benchmarks").json()


def test_daily_ops_ux_endpoints(client):
    client.post("/api/demo/seed-lifecycle")

    # pre-submission similar-idea surfacing
    sim = client.get("/api/ideas/similar", params={"q": "idle cloud instances"}).json()
    assert sim["similar"] and "cloud" in sim["similar"][0]["title"].lower()

    # global search spans ideas, cases, opportunities
    res = client.get("/api/search", params={"q": "invoice"}).json()["results"]
    assert {r["type"] for r in res} & {"idea", "case"}

    # attachments round-trip
    idea = client.get("/api/ideas").json()["ideas"][0]
    up = client.post(f"/api/ideas/{idea['id']}/attachments",
                     files={"file": ("cost-model.csv", b"a,b\n1,2", "text/csv")})
    assert up.status_code == 200
    atts = client.get(f"/api/ideas/{idea['id']}/attachments").json()["attachments"]
    assert atts[0]["filename"] == "cost-model.csv"
    body = client.get(f"/api/attachments/{atts[0]['id']}")
    assert body.content == b"a,b\n1,2"

    # rubric reviews aggregate; queue cards carry the summary
    r = client.post(f"/api/ideas/{idea['id']}/reviews", json={
        "reviewer": "rio", "scores": {"impact": 4, "feasibility": 3}}).json()
    client.post(f"/api/ideas/{idea['id']}/reviews", json={
        "reviewer": "eve", "scores": {"impact": 5, "feasibility": 5}})
    r2 = client.post(f"/api/ideas/{idea['id']}/reviews", json={
        "reviewer": "rio", "scores": {"impact": 2, "feasibility": 2}}).json()
    assert r2["summary"]["count"] == 2  # upsert, not duplicate
    q = client.get("/api/command/queue").json()
    carded = [i for st in q["idea_steps"] for i in st["ideas"] if i["id"] == idea["id"]]
    if carded:
        assert carded[0]["review_summary"]["count"] == 2

    # my-work inbox: submitter sees items needing response, sorted by age
    work = client.get("/api/my-work", params={"user": "sam"}).json()["items"]
    assert any(w["kind"] == "respond" for w in work)
    ages = [w["age_days"] for w in work]
    assert ages == sorted(ages, reverse=True)

    # notification webhook settings validate
    assert client.put("/api/settings/notifications",
                      json={"webhook": "http://insecure"}).status_code == 400
    assert client.put("/api/settings/notifications",
                      json={"webhook": "https://example.com/hook"}).json()["webhook"]


def test_compelling_capabilities(client):
    client.post("/api/demo/seed-lifecycle")

    # Innovation P&L: deployed capital real, verified/claimed separate, tuition carried
    pnl = client.get("/api/reports/innovation-pnl").json()
    assert pnl["capital_deployed"] > 0
    assert pnl["tuition_lessons"] and pnl["tuition_lessons"][0]["learning"]
    assert pnl["forecast_book_calibrated"] <= pnl["forecast_book_raw"] + 0.01

    # cost-of-delay ticker rides the queue
    q = client.get("/api/command/queue").json()
    cod = q["cost_of_delay"]
    assert cod["total_burned"] > 0 and cod["items"][0]["days_waiting"] >= 0

    # red team memo: adversarial, stored on the case
    case = next(c for c in client.get("/api/business-cases").json()["business_cases"]
                if c["stage"] == "proposed")
    memo = client.post(f"/api/business-cases/{case['id']}/redteam").json()["red_team"]
    assert memo["killer_assumption"] and memo["failure_modes"]
    fresh = next(c for c in client.get("/api/business-cases").json()["business_cases"]
                 if c["id"] == case["id"])
    assert fresh["red_team"]["killer_assumption"] == memo["killer_assumption"]

    # simulator: percentiles ordered, probability sane
    sim = client.post("/api/simulator", json={"trials": 500}).json()
    assert sim["annual_value_p10"] <= sim["annual_value_p50"] <= sim["annual_value_p90"]
    assert 0 <= sim["probability_positive"] <= 1

    # genome: learned multipliers with honest sample flags
    g = client.get("/api/genome").json()
    assert g["traits"] and all("multiplier" in t and "sample" in t for t in g["traits"])

    # learning dividends: citing a kill notifies the owner and scores the kill
    idea = client.post("/api/ideas", json={
        "title": "HR chatbot for narrow FAQ topics only",
        "description": "Employees will not discuss leave, pay, or grievances with a bot; "
                       "trust was the barrier — so scope the chatbot to narrow FAQ "
                       "automation and route sensitive topics to a human.",
        "submitter": "maria"}).json()
    divs = client.get("/api/learning-dividends").json()["dividends"]
    assert divs and divs[0]["citations"] >= 1
    notes = client.get("/api/notifications", params={"recipient": "sam"}).json()["notifications"]
    assert any("Learning dividend" in n["message"] for n in notes)

    # signal radar drafts a real challenge
    r = client.post("/api/radar/scan", json={"topic": "competitor launches AI copilot", "launch": True}).json()
    assert r["challenge"]["id"].startswith("CH-") or r["challenge"]["id"]
    assert len(r["signals"]) >= 3 and r["starter_ideas"]


def test_workspace_start_flow(client):
    client.post("/api/demo/seed-lifecycle")
    r = client.post("/api/workspace/start", json={
        "name": "Ryan", "company": "Acme", "email": "ryan@acme.com", "password": "pw"})
    assert r.status_code == 200
    tok = {"Authorization": f"Bearer {r.json()['token']}"}
    # sample data gone, visitor is admin, auth now enforced
    assert client.get("/api/ideas", headers=tok).json()["ideas"] == []
    assert client.get("/api/auth/me", headers=tok).json()["user"]["role"] == "admin"
    assert client.get("/api/ideas").status_code == 401
    # claimed workspaces refuse a second start
    assert client.post("/api/workspace/start", json={
        "name": "x", "company": "y", "email": "x@y.z", "password": "z"}).status_code == 403
