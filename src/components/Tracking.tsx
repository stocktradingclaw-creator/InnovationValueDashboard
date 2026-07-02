import { useState } from 'react'
import { addReading, addSavings, implementCase, money, observeBinding } from '../api'
import type { BusinessCase } from '../types'

function Evidence({ bc, onChanged }: { bc: BusinessCase; onChanged: () => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  if (bc.metric_bindings.length === 0) return null
  return (
    <>
      <h4>Measured evidence <span className="muted small">(frozen baseline, computed from data)</span></h4>
      <table className="kpi-table">
        <thead>
          <tr>
            <th>Metric</th><th className="num">Baseline</th><th className="num">Latest</th>
            <th className="num">Reduction</th><th className="num">Verified /yr</th><th />
          </tr>
        </thead>
        <tbody>
          {bc.metric_bindings.map((b) => (
            <tr key={b.id}>
              <td>
                <strong>{b.label}</strong>
                <div className="muted small">frozen {b.baseline_captured_at.slice(0, 10)} · {b.unit.replace(/_/g, ' ')}</div>
              </td>
              <td className="num">{b.baseline_value.toLocaleString()}</td>
              <td className="num">{b.latest_value != null ? b.latest_value.toLocaleString() : '—'}</td>
              <td className="num">{b.delta != null ? b.delta.toLocaleString() : '—'}</td>
              <td className="num savings">
                {b.latest_value != null && b.baseline_value > 0 && (
                  <svg className="slope" viewBox="0 0 44 18" aria-hidden="true">
                    <line x1="4" y1="5" x2="40"
                          y2={5 + 9 * Math.max(0, Math.min(1, 1 - b.latest_value / b.baseline_value))}
                          className={b.latest_value < b.baseline_value ? 'slope-good' : 'slope-flat'} />
                    <circle cx="40" cy={5 + 9 * Math.max(0, Math.min(1, 1 - b.latest_value / b.baseline_value))} r="2.5"
                            className={b.latest_value < b.baseline_value ? 'slope-dot-good' : 'slope-dot-flat'} />
                  </svg>
                )}
                {b.annualized_delta != null ? money(b.annualized_delta) : '—'}
              </td>
              <td>
                <button
                  className="secondary"
                  disabled={busy === b.id}
                  onClick={async () => {
                    setBusy(b.id)
                    try {
                      await observeBinding(bc.id, b.id)
                      onChanged()
                    } finally {
                      setBusy(null)
                    }
                  }}
                >
                  {busy === b.id ? 'Observing…' : 'Observe now'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

interface Props {
  cases: BusinessCase[]
  onChanged: () => void
}

const today = () => new Date().toISOString().slice(0, 10)

function ImplementForm({ bc, onChanged }: { bc: BusinessCase; onChanged: () => void }) {
  const [goLive, setGoLive] = useState(today())
  const [busy, setBusy] = useState(false)
  return (
    <div className="row">
      <span className="muted small">Not yet implemented — set a go-live date to start tracking:</span>
      <input type="date" value={goLive} onChange={(e) => setGoLive(e.target.value)} />
      <button
        disabled={busy || !goLive}
        onClick={async () => {
          setBusy(true)
          try {
            await implementCase(bc.id, goLive)
            onChanged()
          } finally {
            setBusy(false)
          }
        }}
      >
        Mark implemented
      </button>
    </div>
  )
}

function SavingsForm({ bc, onChanged }: { bc: BusinessCase; onChanged: () => void }) {
  const [date, setDate] = useState(today())
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="row">
      <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      <input
        type="number"
        placeholder="Realized savings (USD)"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <button
        disabled={busy || !amount}
        onClick={async () => {
          setBusy(true)
          try {
            await addSavings(bc.id, { entry_date: date, amount: Number(amount), note: note || undefined })
            setAmount('')
            setNote('')
            onChanged()
          } finally {
            setBusy(false)
          }
        }}
      >
        Record savings
      </button>
    </div>
  )
}

function ReadingForm({ bc, onChanged }: { bc: BusinessCase; onChanged: () => void }) {
  const [kpi, setKpi] = useState(bc.roi_plan.kpis[0]?.name ?? '')
  const [date, setDate] = useState(today())
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <>
      <div className="row">
        <select value={kpi} onChange={(e) => setKpi(e.target.value)}>
          {bc.roi_plan.kpis.map((k) => (
            <option key={k.name} value={k.name}>
              {k.name}
            </option>
          ))}
        </select>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <input
          type="number"
          placeholder="Value"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button
          disabled={busy || !kpi || value === ''}
          onClick={async () => {
            setBusy(true)
            setError(null)
            try {
              await addReading(bc.id, { kpi_name: kpi, reading_date: date, value: Number(value) })
              setValue('')
              onChanged()
            } catch (e) {
              setError(e instanceof Error ? e.message : String(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          Record reading
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}

function CaseTracker({ bc, onChanged }: { bc: BusinessCase; onChanged: () => void }) {
  const t = bc.tracking
  const readingsByKpi = new Map<string, typeof bc.kpi_readings>()
  for (const r of bc.kpi_readings) {
    const list = readingsByKpi.get(r.kpi_name) ?? []
    list.push(r)
    readingsByKpi.set(r.kpi_name, list)
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>{bc.title}</h3>
        <div className="row">
          {bc.go_live_date && <span className="muted small">live since {bc.go_live_date}</span>}
          <span className={bc.status === 'implemented' ? 'badge badge-ok' : 'badge'}>
            {bc.status}
          </span>
        </div>
      </div>

      {bc.status === 'proposed' && <ImplementForm bc={bc} onChanged={onChanged} />}

      {bc.status === 'proposed' && <Evidence bc={bc} onChanged={onChanged} />}

      {bc.status === 'implemented' && t && (
        <>
          <div className="metrics-row">
            <div className="metric">
              <span className="muted small">Verified /yr (measured)</span>
              <strong className={t.measured_annual_savings > 0 ? 'pos' : ''}>
                {money(t.measured_annual_savings)}
              </strong>
            </div>
            <div className="metric">
              <span className="muted small">Claimed savings</span>
              <strong>{money(t.total_realized_savings)}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Est. cost</span>
              <strong>{bc.estimated_cost != null ? money(bc.estimated_cost) : '—'}</strong>
            </div>
            <div className="metric">
              <span className="muted small">Realized ROI</span>
              <strong className={t.realized_roi_pct != null && t.realized_roi_pct >= 0 ? 'pos' : 'neg'}>
                {t.realized_roi_pct != null ? `${t.realized_roi_pct}%` : '—'}
              </strong>
            </div>
            <div className="metric">
              <span className="muted small">Months live</span>
              <strong>{t.months_live ?? '—'}</strong>
            </div>
          </div>

          {t.payback_progress_pct != null && (
            <div className="progress-wrap">
              <span className="muted small">Payback progress</span>
              <div className="progress">
                <div className="progress-bar" style={{ width: `${t.payback_progress_pct}%` }} />
              </div>
              <span className="small">{t.payback_progress_pct}%</span>
            </div>
          )}

          <Evidence bc={bc} onChanged={onChanged} />

          <h4>Record claimed savings <span className="muted small">(self-reported)</span></h4>
          <SavingsForm bc={bc} onChanged={onChanged} />
          {bc.savings_entries.length > 0 && (
            <table className="kpi-table">
              <thead>
                <tr><th>Date</th><th className="num">Amount</th><th>Note</th></tr>
              </thead>
              <tbody>
                {bc.savings_entries.map((s) => (
                  <tr key={s.id}>
                    <td>{s.entry_date}</td>
                    <td className="num savings">{money(s.amount)}</td>
                    <td className="muted">{s.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h4>KPI readings</h4>
          <ReadingForm bc={bc} onChanged={onChanged} />
          {bc.roi_plan.kpis.map((k) => {
            const readings = readingsByKpi.get(k.name) ?? []
            return (
              <div key={k.name} className="kpi-track">
                <strong>{k.name}</strong>{' '}
                <span className="muted small">target: {k.target}</span>
                {readings.length === 0 ? (
                  <p className="muted small">No readings yet. Baseline: {k.baseline_method}</p>
                ) : (
                  <table className="kpi-table">
                    <thead>
                      <tr><th>Date</th><th className="num">Value</th><th>Note</th></tr>
                    </thead>
                    <tbody>
                      {readings.map((r) => (
                        <tr key={r.id}>
                          <td>{r.reading_date}</td>
                          <td className="num">{r.value.toLocaleString()}</td>
                          <td className="muted">{r.note}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </>
      )}
    </div>
  )
}

export default function Tracking({ cases, onChanged }: Props) {
  if (cases.length === 0) {
    return (
      <section>
        <h2>ROI tracking</h2>
        <p className="muted">
          No business cases yet. Submit one under <strong>Business Cases</strong>, then come back
          here after implementation to record KPI readings and realized savings against the plan.
        </p>
      </section>
    )
  }
  const implemented = cases.filter((c) => c.status === 'implemented')
  const proposed = cases.filter((c) => c.status === 'proposed')
  return (
    <section>
      <h2>ROI tracking</h2>
      <p className="muted">
        Record actuals against each ROI plan after go-live: realized savings drive ROI and payback;
        KPI readings show whether the value drivers are moving.
      </p>
      {[...implemented, ...proposed].map((c) => (
        <CaseTracker key={c.id} bc={c} onChanged={onChanged} />
      ))}
    </section>
  )
}
