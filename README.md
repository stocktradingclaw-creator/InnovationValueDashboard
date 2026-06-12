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
  - Business-case digestion via Claude (`messages.parse` structured output);
    falls back to a deterministic template plan when no API key is set.
    Cases can link to a detected opportunity — the link feeds the prompt so
    KPIs anchor to the customer's own data
  - Post-implementation tracking: mark a case implemented, record realized
    savings and KPI readings; the API computes realized ROI, payback
    progress, and months live
- `src/` — React + TypeScript frontend (Vite)
  - **Data Sources** — upload CSVs, load sample data, or sync live connectors
  - **Opportunities** — savings-ranked table with effort/confidence and drill-down
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
| `GET` | `/api/opportunities` | Run the rules engine over loaded data |
| `POST` | `/api/business-cases` | Digest a business case (optional `linked_opportunity_id`) |
| `GET` | `/api/business-cases` | List cases with plans, readings, savings, tracking |
| `POST` | `/api/business-cases/{id}/implement` | Mark implemented with a go-live date |
| `POST` | `/api/business-cases/{id}/readings` | Record a KPI reading (must match a plan KPI) |
| `POST` | `/api/business-cases/{id}/savings` | Record realized savings (drives ROI/payback) |

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
  opportunities for investigation — not financial commitments.
- Connector field mappings ship with common defaults (e.g. ServiceNow
  `u_environment`, SAP `GrossAmount`); real instances usually need a custom
  `field_map` in the sync request body.
- Cloud billing remains CSV-based (use a Cost & Usage Report export).
- Connector credentials travel over plain HTTP to localhost — front the API
  with TLS before deploying anywhere shared.
