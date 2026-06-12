# InnovationValueDashboard

A value-engineering dashboard in the spirit of Celonis: feed in a customer's
**CMDB, ERP, cloud billing, and ITSM** data and it surfaces ranked
**cost-reduction opportunities**. Then feed in a **business case** for an
improvement idea and it digests the text (via the Claude API) into a concrete
**ROI measurement plan** — KPIs, baselines, data sources, cadence, and the ROI
formula to apply after implementation.

## Architecture

- `server/` — FastAPI backend (Python)
  - CSV importers for 4 source types with column validation
  - Rules engine: idle/EOL infrastructure, app rationalization, duplicate
    payments, vendor consolidation, maverick spend, cloud rightsizing,
    orphaned storage, ITSM automation candidates, incident hotspots
  - Business-case digestion via Claude (`messages.parse` structured output);
    falls back to a deterministic template plan when no API key is set
- `src/` — React + TypeScript frontend (Vite)
  - **Data Sources** — upload customer CSVs or load bundled sample data
  - **Opportunities** — savings-ranked table with effort/confidence and drill-down
  - **Business Cases** — submit an idea, get the generated ROI plan

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
| `GET` | `/api/datasets` | Source types, required columns, rows loaded |
| `POST` | `/api/datasets/{source_type}` | Upload a CSV (`cmdb`, `erp`, `cloud`, `itsm`) |
| `POST` | `/api/datasets/load-samples` | Load bundled synthetic sample data |
| `GET` | `/api/opportunities` | Run the rules engine over loaded data |
| `POST` | `/api/business-cases` | Digest a business case into an ROI plan |
| `GET` | `/api/business-cases` | List submitted cases and their plans |

## Notes

- Savings figures are conservative heuristics meant to rank and size
  opportunities for investigation — not financial commitments.
- Data is held in memory; restarting the server clears it. Swap
  `server/app/store.py` for a database when persistence matters.
