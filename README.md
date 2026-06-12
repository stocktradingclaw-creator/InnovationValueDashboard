# InnovationValueDashboard

A value-engineering dashboard in the spirit of Celonis: feed in a customer's
**CMDB, ERP, cloud billing, and ITSM** data and it surfaces ranked
**cost-reduction opportunities**. Then feed in a **business case** for an
improvement idea and it digests the text (via the Claude API) into a concrete
**ROI measurement plan** — KPIs, baselines, data sources, cadence, and the ROI
formula to apply after implementation.

## Architecture

- `server/` — FastAPI backend (Python)
  - SQLite persistence (`server/data.db`) — datasets, cases, readings, and
    savings survive restarts
  - CSV importers for 4 source types with column validation
  - Live connectors: **ServiceNow Table API** (CMDB CIs, incidents + service
    requests) and **SAP OData** (invoice line items). Credentials are used
    per-sync and never stored; field mappings are overridable per instance
  - Rules engine: idle/EOL infrastructure, app rationalization, duplicate
    payments, vendor consolidation, maverick spend, cloud rightsizing,
    orphaned storage, ITSM automation candidates, incident hotspots
  - Prioritization model: each opportunity is scored 0-100 from
    **value** (risk-adjusted savings = savings x detection confidence,
    log-scaled), **efficiency** (payback ratio vs. an effort-and-scale-based
    implementation cost estimate), **speed** (time to value), and
    **simplicity** (inverse of complexity). Weights are tunable per request;
    opportunities get value-vs-effort quadrant labels (quick win / strategic
    bet / fill-in / deprioritize), payback months, and 1-/3-year net figures
  - Complexity rating per opportunity (low / medium / high / very high):
    each rule assigns the intrinsic coordination burden and delivery risk of
    the play (e.g. app rationalization is high; deleting orphaned volumes is
    low), bumped upward when the blast radius is large (15+ / 75+ affected
    items). Distinct from effort, which approximates labor/cost
  - Business-case digestion via Claude (`messages.parse` structured output);
    falls back to a deterministic template plan when no API key is set.
    Cases can link to a detected opportunity — the link feeds the prompt so
    KPIs anchor to the customer's own data
  - Post-implementation tracking: mark a case implemented, record realized
    savings and KPI readings; the API computes realized ROI, payback
    progress, and months live
  - **Measurement objectivity** — three mechanisms that shrink the
    subjectivity of value claims:
    - *Metric bindings with frozen baselines*: every detection rule ships a
      computable measure (a declarative query over the ingested data).
      Linking a business case to an opportunity freezes the baseline at
      creation; later observations run the identical query against fresh
      data. Verified value is computed, never typed. (`app/metrics.py`)
    - *Calibration loop*: implemented cases yield realization rates
      (actual vs. forecast) per opportunity category, which automatically
      discount or boost future estimates of the same category in the
      prioritization model. (`app/calibration.py`, `GET /api/calibration`)
    - *Auditor pass*: Claude classifies each KPI's objectivity (hard /
      medium / soft) and flags business-case claims that no named data
      source can verify (`unmeasurable_claims`)
  - Tracking reports **verified** (measured from data) and **claimed**
    (self-reported) value as separate numbers — never blended
  - **Value against time**: monthly portfolio series built from recorded
    events — implementation cost lands at go-live, claimed savings at their
    entry dates, verified value accrues from the month each binding
    observation lands (no retroactive credit). Computes portfolio ROI over
    time and a projected break-even month at the current verified run-rate
    (`app/timeline.py`, included in `GET /api/dashboard`)
  - **Portfolio value diagnostic**: ingest an existing initiative portfolio
    (PMO export, 5th source type `portfolio`) and diagnose value leaks —
    unverified benefit claims, realization shortfalls, weak ROI, budget
    overruns, stalled delivery, parked spend, concentration risk, soft-benefit
    reliance, overlapping scope. Produces a health score, portfolio stats,
    and severity-ranked findings with value impact
    (`app/portfolio.py`, `GET /api/portfolio/diagnostic`)
- `src/` — React + TypeScript frontend (Vite)
  - **Overview** — board-grade dashboard: a plain-English headline, hero
    stats (verified run-rate, invested, return multiple, break-even,
    portfolio health), a ranked **decision queue** (approve / fund / verify /
    intervene, by annual value at stake), the value trajectory chart with
    projection, value conversion funnel, a "confidence in these numbers"
    panel, delivery pipeline, and a data-freshness strip
  - **Data Sources** — upload CSVs, load sample data, or sync live connectors
  - **Opportunities** — score-ranked table with weight sliders, a
    value-vs-effort quadrant matrix, and per-opportunity economics drill-down
  - **Business Cases** — submit an idea (optionally linked to an opportunity),
    get the generated ROI plan
  - **ROI Tracking** — record actuals against each plan after go-live

## Getting started

### Backend

```bash
cd server
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # optional; enables AI-generated ROI plans
.venv/bin/uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
npm install
npm run dev
```

Open http://localhost:5173, click **Load sample data**, then explore the
Opportunities and Business Cases tabs.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/datasets` | Source types, required columns, rows loaded, origin |
| `POST` | `/api/datasets/{source_type}` | Upload a CSV (`cmdb`, `erp`, `cloud`, `itsm`) |
| `POST` | `/api/datasets/load-samples` | Load bundled synthetic sample data |
| `POST` | `/api/connectors/servicenow/sync` | Pull CMDB or ITSM data from a ServiceNow instance |
| `POST` | `/api/connectors/sap/sync` | Pull ERP invoices from an SAP OData service |
| `GET` | `/api/opportunities` | Rules engine + prioritization (optional `value_weight`, `efficiency_weight`, `speed_weight`, `simplicity_weight`) |
| `POST` | `/api/business-cases` | Digest a business case (optional `linked_opportunity_id`) |
| `GET` | `/api/business-cases` | List cases with plans, readings, savings, tracking |
| `POST` | `/api/business-cases/{id}/implement` | Mark implemented with a go-live date |
| `POST` | `/api/business-cases/{id}/readings` | Record a KPI reading (must match a plan KPI) |
| `POST` | `/api/business-cases/{id}/savings` | Record claimed savings (drives ROI/payback) |
| `POST` | `/api/business-cases/{id}/bindings` | Create a metric binding (freezes the baseline now) |
| `POST` | `/api/business-cases/{id}/bindings/{bid}/observe` | Re-run the binding's query against current data |
| `GET` | `/api/calibration` | Realization rates per opportunity category |
| `GET` | `/api/dashboard` | Consolidated overview payload (funnel, mix, pipeline, calibration, freshness) |

## Tests

```bash
cd server
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/
```

Connector tests run against mocked HTTP responses — no live ServiceNow/SAP
instance needed.

## Notes

- Savings figures are conservative heuristics meant to rank and size
  opportunities for investigation — not financial commitments. The same goes
  for the prioritization model's implementation-cost and time-to-value
  estimates (see `server/app/prioritization.py` to tune the constants).
- Connector field mappings ship with common defaults (e.g. ServiceNow
  `u_environment`, SAP `GrossAmount`); real instances usually need a custom
  `field_map` in the sync request body.
- Cloud billing remains CSV-based (use a Cost & Usage Report export).
- Connector credentials travel over plain HTTP to localhost — front the API
  with TLS before deploying anywhere shared.
