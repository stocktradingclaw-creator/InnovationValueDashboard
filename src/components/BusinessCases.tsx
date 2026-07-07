import { useState } from 'react'
import { useEffect } from 'react'
import { assistDescription, money, submitBusinessCase, toast } from '../api'
import type { BusinessCase, Opportunity, ROIPlan } from '../types'

interface Props {
  cases: BusinessCase[]
  opportunities: Opportunity[]
  onChanged: () => void
}

interface Financials {
  annual_benefit: number; implementation_cost: number; tcv: number; total_cost: number
  npv: number; roi_pct: number | null; payback_months: number | null
  cash_flows: { year: number; benefit: number; cost: number; net: number }[]
  data_grounding: string[]; assumptions: string[]; benefit_basis: string
}

function CfoView({ caseId }: { caseId: string }) {
  const [fin, setFin] = useState<Financials | null>(null)
  const [horizon, setHorizon] = useState(3)
  const [rate, setRate] = useState(0.10)
  useEffect(() => {
    fetch(`/api/business-cases/${caseId}/financials?horizon_years=${horizon}&discount_rate=${rate}`)
      .then((r) => r.json()).then(setFin).catch(() => {})
  }, [caseId, horizon, rate])
  if (!fin) return null
  return (
    <div className="plan">
      <div className="card-header">
        <h4>CFO view — quantified from {fin.benefit_basis === 'verified' ? 'VERIFIED actuals'
          : fin.benefit_basis === 'detected_opportunity' ? "the customer's own data" : 'submitter estimates'}</h4>
        <div className="row">
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}
                  aria-label="Horizon">
            {[1, 3, 5, 7].map((y) => <option key={y} value={y}>{y}-year horizon</option>)}
          </select>
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))}
                  aria-label="Discount rate">
            {[0.08, 0.10, 0.12, 0.15].map((r) => <option key={r} value={r}>{Math.round(r * 100)}% discount</option>)}
          </select>
        </div>
      </div>
      <div className="metrics-row">
        <div className="metric"><span className="muted small">ROI ({horizon}yr)</span>
          <strong className={fin.roi_pct != null && fin.roi_pct >= 0 ? 'pos' : 'neg'}>
            {fin.roi_pct != null ? `${fin.roi_pct}%` : '—'}</strong></div>
        <div className="metric"><span className="muted small">NPV @ {Math.round(rate * 100)}%</span>
          <strong className={fin.npv >= 0 ? 'pos' : 'neg'}>{money(fin.npv)}</strong></div>
        <div className="metric"><span className="muted small">TCV ({horizon}yr benefits)</span>
          <strong>{money(fin.tcv)}</strong></div>
        <div className="metric"><span className="muted small">Payback</span>
          <strong>{fin.payback_months != null ? `${fin.payback_months} mo` : '—'}</strong></div>
        <div className="metric"><span className="muted small">Total cost ({horizon}yr)</span>
          <strong>{money(fin.total_cost)}</strong></div>
      </div>
      <table className="kpi-table">
        <thead><tr><th>Year</th><th className="num">Benefit</th><th className="num">Cost</th><th className="num">Net</th></tr></thead>
        <tbody>
          {fin.cash_flows.map((cf) => (
            <tr key={cf.year}><td>Y{cf.year}</td>
              <td className="num">{money(cf.benefit)}</td>
              <td className="num">{money(cf.cost)}</td>
              <td className="num savings">{money(cf.net)}</td></tr>
          ))}
        </tbody>
      </table>
      {fin.data_grounding.length > 0 && (
        <ul className="small">{fin.data_grounding.map((g) => <li key={g}>✓ {g}</li>)}</ul>
      )}
      {fin.assumptions.length > 0 && (
        <ul className="muted small">{fin.assumptions.map((a) => <li key={a}>• {a}</li>)}</ul>
      )}
    </div>
  )
}

function PlanView({ plan }: { plan: ROIPlan }) {
  return (
    <div className="plan">
      <p>{plan.summary}</p>

      {plan.unmeasurable_claims && plan.unmeasurable_claims.length > 0 && (
        <div className="banner-warn">
          <strong>Unmeasurable claims flagged:</strong> the business case makes claims no named
          data source can verify —
          <ul>
            {plan.unmeasurable_claims.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      <h4>Value drivers</h4>
      <ul>
        {plan.value_drivers.map((v) => (
          <li key={v.name}>
            <strong>{v.name}</strong> <span className="tag">{v.driver_type}</span>
            <div className="muted small">{v.description}</div>
          </li>
        ))}
      </ul>

      <h4>KPIs</h4>
      <table className="kpi-table">
        <thead>
          <tr>
            <th>KPI</th>
            <th>Formula</th>
            <th>Baseline</th>
            <th>Target</th>
            <th>Sources</th>
            <th>Cadence</th>
            <th>Type</th>
            <th>Objectivity</th>
          </tr>
        </thead>
        <tbody>
          {plan.kpis.map((k) => (
            <tr key={k.name} className={k.objectivity ? `obj-row-${k.objectivity}` : ''}>
              <td><strong>{k.name}</strong></td>
              <td>{k.formula}</td>
              <td>{k.baseline_method}</td>
              <td>{k.target}</td>
              <td>{k.data_sources.join(', ')}</td>
              <td>{k.cadence}</td>
              <td>
                <span className={`pill pill-${k.indicator_type === 'leading' ? 'low' : 'medium'}`}>
                  {k.indicator_type}
                </span>
              </td>
              <td>
                {k.objectivity ? (
                  <span className={`pill obj-${k.objectivity}`}>{k.objectivity}</span>
                ) : (
                  <span className="muted small">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4>How ROI is computed</h4>
      <p className="formula">{plan.roi_formula}</p>
      <p>
        <strong>Baseline plan:</strong> {plan.baseline_plan}
      </p>
      <p className="muted">
        Measure {plan.measurement_cadence}, for {plan.measurement_duration}.
      </p>

      <div className="two-col">
        <div>
          <h4>Assumptions</h4>
          <ul>
            {plan.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4>Measurement risks</h4>
          <ul>
            {plan.measurement_risks.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

export default function BusinessCases({ cases, opportunities, onChanged }: Props) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [cost, setCost] = useState('')
  const [linkedOpp, setLinkedOpp] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const created = await submitBusinessCase({
        title,
        description,
        estimated_cost: cost ? Number(cost) : null,
        linked_opportunity_id: linkedOpp || null,
      })
      setTitle('')
      setDescription('')
      setCost('')
      setLinkedOpp('')
      setExpanded(created.id)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h2>Business cases &amp; ROI measurement</h2>
      <p className="muted">
        Paste a business case below. The engine digests it and designs how to measure the ROI of
        the idea after implementation — KPIs, baselines, data sources, and the ROI formula.
      </p>

      <div className="card bc-form">
        <input
          placeholder="Title — e.g. Automate password resets with self-service"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea
          rows={6}
          placeholder="Describe the idea: the problem today, the proposed change, who benefits, and any savings claims…"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
        <div className="row">
          <button type="button" className={description.trim() ? 'secondary' : ''}
                  disabled={!title.trim()}
                  onClick={async () => {
                    const r = await assistDescription({ title, description: description || undefined })
                    setDescription(r.draft)
                    toast(r.mode === 'generate' ? 'Draft written — edit before submitting.' : 'Description reviewed and tightened.')
                  }}>
            ✦ {description.trim() ? 'Review & improve' : 'Draft with AI'}
          </button>
        </div>
        <select value={linkedOpp} onChange={(e) => setLinkedOpp(e.target.value)}>
          <option value="">No linked opportunity (standalone idea)</option>
          {opportunities.map((o) => (
            <option key={o.id} value={o.id}>
              {o.title} — {money(o.estimated_annual_savings)}/yr detected
            </option>
          ))}
        </select>
        <div className="row">
          <input
            type="number"
            placeholder="Estimated implementation cost (USD, optional)"
            value={cost}
            onChange={(e) => setCost(e.target.value)}
          />
          <button disabled={busy || !title.trim() || !description.trim()} onClick={submit}>
            {busy ? 'Analyzing…' : 'Digest & build ROI plan'}
          </button>
        </div>
        {busy && <p className="muted">Analyzing the business case — this can take a minute…</p>}
        {error && <p className="error">{error}</p>}
      </div>

      {cases.map((c) => (
        <div key={c.id} className="card bc-card">
          <div
            className="card-header clickable"
            role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(expanded === c.id ? null : c.id) } }} onClick={() => setExpanded(expanded === c.id ? null : c.id)}
          >
            <h3>{c.title}</h3>
            <div className="row">
              {c.estimated_cost != null && (
                <span className="muted">{money(c.estimated_cost)} est. cost</span>
              )}
              {c.status === 'implemented' && <span className="badge badge-ok">implemented</span>}
              <span className={c.generated_by === 'claude' ? 'badge badge-ok' : 'badge'}>
                {c.generated_by === 'claude' ? 'AI plan' : 'template plan'}
              </span>
            </div>
          </div>
          {c.linked_opportunity && (
            <p className="muted small">
              Linked opportunity: <strong>{c.linked_opportunity.title}</strong> (
              {money(c.linked_opportunity.estimated_annual_savings)}/yr detected)
            </p>
          )}
          {c.note && <p className="muted small">{c.note}</p>}
          {expanded === c.id && <><CfoView caseId={c.id} /><PlanView plan={c.roi_plan} /></>}
        </div>
      ))}
    </section>
  )
}
