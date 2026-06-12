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
