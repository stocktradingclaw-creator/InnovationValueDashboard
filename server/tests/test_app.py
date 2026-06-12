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

    # plain-English headline reflects the no-cases-yet state
    assert "quick wins" in dash["headline"]
    assert dash["portfolio_health"] is not None  # sample portfolio loaded

    decisions = dash["decisions"]
    assert 0 < len(decisions) <= 6
    actions = {d["action"] for d in decisions}
    assert "approve" in actions          # unaddressed quick wins
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
