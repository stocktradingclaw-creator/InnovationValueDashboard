import { useState } from 'react'
import { money, submitBusinessCase } from '../api'
import type { BusinessCase, Opportunity, ROIPlan } from '../types'

interface Props {
  cases: BusinessCase[]
  opportunities: Opportunity[]
  onChanged: () => void
}

function PlanView({ plan }: { plan: ROIPlan }) {
  return (
    <div className="plan">
      <p>{plan.summary}</p>

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
          </tr>
        </thead>
        <tbody>
          {plan.kpis.map((k) => (
            <tr key={k.name}>
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
            onClick={() => setExpanded(expanded === c.id ? null : c.id)}
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
          {expanded === c.id && <PlanView plan={c.roi_plan} />}
        </div>
      ))}
    </section>
  )
}
