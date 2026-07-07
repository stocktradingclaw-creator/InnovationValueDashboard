import { useEffect, useRef, useState } from 'react'
import { getPortfolioDiagnostic, money, runSimulator, uploadDataset } from '../api'
import type { PortfolioReport } from '../types'

interface Props {
  report: PortfolioReport | null
  hasPortfolio: boolean
  onChanged: () => void
}

const SEVERITY_LABEL: Record<string, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

function scoreClass(score: number) {
  if (score >= 70) return 'score-good'
  if (score >= 40) return 'score-warn'
  return 'score-bad'
}

interface Advisory {
  purpose: string; total_pipeline_value: number
  balance: { horizon: string; share: number; target: number; verdict: string }[]
  concentration_top_case: number
  peer_comparison: { metric: string; ours: number | null; peer_low: number; peer_high: number; note: string; verdict: string | null }[]
  peer_note: string
  recommendations: { key: string | null; title: string; why: string; action: string }[]
}

const H_LABELS: Record<string, string> = { h1: 'H1 · Core', h2: 'H2 · Adjacent', h3: 'H3 · Transformational' }

function AdvisoryPanel() {
  const [a, setA] = useState<Advisory | null>(null)
  const [execBusy, setExecBusy] = useState<string | null>(null)
  const [execResult, setExecResult] = useState<Record<string, string>>({})
  const reload = () => fetch('/api/portfolio/advisory').then((r) => r.json()).then(setA).catch(() => {})
  useEffect(() => {
    fetch('/api/portfolio/advisory').then((r) => r.json()).then(setA).catch(() => {})
  }, [])
  if (!a) return null
  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3>Portfolio balance — vs the 70 / 20 / 10 target</h3>
          <span className="muted small">{money(a.total_pipeline_value)}/yr active pipeline</span>
        </div>
        {a.balance.map((b) => (
          <div key={b.horizon} className="initiative-row">
            <div className="initiative-head">
              <strong>{H_LABELS[b.horizon] ?? b.horizon}</strong>
              <span className={`pill ${b.verdict === 'on-target' ? 'act-approve' : 'act-verify'}`}>
                {Math.round(b.share * 100)}% vs {Math.round(b.target * 100)}% target · {b.verdict}
              </span>
            </div>
            <div className="funnel-track">
              <div className="funnel-bar stage-committed" style={{ width: `${b.share * 100}%` }} />
            </div>
            <div className="funnel-track thin">
              <div className="funnel-bar stage-verified" style={{ width: `${b.target * 100}%` }} />
            </div>
          </div>
        ))}
        <p className="muted small">
          Top bar: your share of pipeline value. Thin bar: target. Single-bet concentration:{' '}
          <strong>{Math.round(a.concentration_top_case * 100)}%</strong> of value in the largest case.
        </p>
      </div>

      <div className="card">
        <h3>How this portfolio compares to peers</h3>
        <table className="kpi-table">
          <thead><tr><th>Metric</th><th className="num">You</th><th className="num">Peer range</th><th>Read</th></tr></thead>
          <tbody>
            {a.peer_comparison.map((p) => (
              <tr key={p.metric}>
                <td><strong>{p.metric}</strong><div className="muted small">{p.note}</div></td>
                <td className="num">{p.ours != null ? `${Math.round(p.ours * 100)}%` : '—'}</td>
                <td className="num muted">{Math.round(p.peer_low * 100)}–{Math.round(p.peer_high * 100)}%</td>
                <td>{p.verdict
                  ? <span className={`pill ${p.verdict === 'in-range' ? 'act-approve' : 'act-verify'}`}>{p.verdict}</span>
                  : <span className="muted small">no data yet</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">{a.peer_note}</p>
      </div>

      <div className="card">
        <h3>Recommended actions</h3>
        {a.recommendations.map((r) => (
          <div key={r.title} className="decision-row">
            <span className="pill act-verify">act</span>
            <span style={{ flex: 1 }}><strong>{r.title}</strong> <span className="muted small">{r.why}</span>
              <div className="small">→ {r.action}</div>
              {execResult[r.key ?? ''] && (
                <div className="success small">✓ {execResult[r.key ?? '']}</div>
              )}</span>
            {r.key && !execResult[r.key] && (
              <button disabled={execBusy === r.key} onClick={async () => {
                setExecBusy(r.key)
                try {
                  const res = await fetch('/api/portfolio/advisory/execute', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key: r.key }),
                  })
                  const d = await res.json()
                  if (!res.ok) throw new Error(d.detail ?? 'execution failed')
                  setExecResult((x) => ({ ...x, [r.key!]: d.done }))
                  reload()
                } catch (e) {
                  setExecResult((x) => ({ ...x, [r.key!]: e instanceof Error ? e.message : String(e) }))
                } finally { setExecBusy(null) }
              }}>{execBusy === r.key ? 'Executing…' : '⚡ Execute'}</button>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

function Simulator() {
  const [sim, setSim] = useState<Awaited<ReturnType<typeof runSimulator>> | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="card">
      <div className="card-header">
        <h3>Portfolio simulator</h3>
        <button className="secondary" disabled={busy} onClick={async () => {
          setBusy(true)
          try { setSim(await runSimulator()) } finally { setBusy(false) }
        }}>{busy ? 'Simulating…' : 'Run 2,000 futures'}</button>
      </div>
      <p className="muted small">
        Monte Carlo over the active pipeline, sampling realization from calibration factors
        learned from actuals — probability-weighted outcomes, not point estimates.
      </p>
      {sim && sim.cases > 0 && (
        <>
          <div className="metrics-row">
            <div className="metric"><span className="muted small">Pessimistic (p10) /yr</span>
              <strong>{money(sim.annual_value_p10)}</strong></div>
            <div className="metric"><span className="muted small">Expected (p50) /yr</span>
              <strong className="pos">{money(sim.annual_value_p50)}</strong></div>
            <div className="metric"><span className="muted small">Optimistic (p90) /yr</span>
              <strong>{money(sim.annual_value_p90)}</strong></div>
            <div className="metric"><span className="muted small">P(net positive)</span>
              <strong>{Math.round(sim.probability_positive * 100)}%</strong></div>
          </div>
          <p className="small">
            <strong>
              {sim.annual_value_p10 > 0
                ? 'Even the pessimistic run pays for itself — this portfolio is robust, not lucky.'
                : sim.probability_positive >= 0.7
                  ? `${Math.round(sim.probability_positive * 100)}% of futures end net positive — fund it, but stage the tranches.`
                  : 'Too many futures end underwater — de-risk with experiments before committing capital.'}
            </strong>
          </p>
          <p className="muted small">
            {sim.cases} active case(s), {sim.trials.toLocaleString()} trials · median per case:{' '}
            {sim.per_case.slice(0, 4).map((c) => `${c.title} ${money(c.p50)}`).join(' · ')}
          </p>
        </>
      )}
    </div>
  )
}

export default function Portfolio({ report, hasPortfolio, onChanged }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const upload = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      await uploadDataset('portfolio', file)
      await getPortfolioDiagnostic()
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Portfolio advisory</h2>
          <p className="muted">
            The management window on your innovation portfolio: balance against the 70/20/10
            target, position vs industry peers, recommended actions, simulated futures — and a
            diagnostic for external PMO exports below.
          </p>
        </div>
        <div>
          <input
            ref={fileInput}
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
          />
          <button disabled={busy} onClick={() => fileInput.current?.click()}>
            {busy ? 'Analyzing…' : hasPortfolio ? 'Replace portfolio CSV' : 'Upload portfolio CSV'}
          </button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <AdvisoryPanel />
      <Simulator />
      <h3 className="spaced">Diagnose an external portfolio (PMO export)</h3>

      {!report ? (
        <p className="muted">
          No portfolio loaded. Upload a CSV with columns:{' '}
          <code>
            initiative_id, name, status, budget, claimed_annual_benefit
          </code>{' '}
          (optional: <code>spend_to_date, measured_annual_benefit, benefit_type, category,
          start_date, go_live_date</code>) — or load the sample data from Data Sources.
        </p>
      ) : (
        <>
          <div className="metrics-row headline-row">
            <div className={`metric headline score ${scoreClass(report.health_score)}`}>
              <span className="muted small">Portfolio health</span>
              <span className="gauge-wrap">
                <svg viewBox="0 0 42 42" className="gauge" aria-hidden="true">
                  <circle className="gauge-bg" cx="21" cy="21" r="16" pathLength={100} />
                  <circle className={`gauge-fg ${report.health_score >= 70 ? 'g-good' : report.health_score >= 40 ? 'g-warn' : 'g-bad'}`}
                          cx="21" cy="21" r="16" pathLength={100} strokeDasharray={`${report.health_score} 100`} />
                </svg>
                <strong>{report.health_score}/100</strong>
              </span>
            </div>
            <div className="metric headline">
              <span className="muted small">Initiatives</span>
              <strong>{report.stats.initiatives}</strong>
            </div>
            <div className="metric headline">
              <span className="muted small">Budget / spend</span>
              <strong>
                {money(report.stats.total_budget)}{' '}
                <span className="muted small">/ {money(report.stats.total_spend_to_date)}</span>
              </strong>
            </div>
            <div className="metric headline">
              <span className="muted small">Claimed /yr</span>
              <strong>{money(report.stats.total_claimed_annual_benefit)}</strong>
            </div>
            <div className="metric headline verified">
              <span className="muted small">Measured /yr</span>
              <strong>{money(report.stats.total_measured_annual_benefit)}</strong>
            </div>
          </div>

          {report.stats.verification_ratio != null && (
            <div className="progress-wrap">
              <span className="muted small">Benefit verification</span>
              <div className="progress">
                <div
                  className="progress-bar"
                  style={{ width: `${Math.min(report.stats.verification_ratio * 100, 100)}%` }}
                />
              </div>
              <span className="small">
                {Math.round(report.stats.verification_ratio * 100)}% of claimed value is measured
              </span>
            </div>
          )}

          <h3 className="spaced">
            Findings ({report.findings.length})
          </h3>
          {report.findings.map((f) => (
            <div key={f.title} className={`card finding sev-border-${f.severity}`}>
              <div
                className="card-header clickable"
                role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(expanded === f.title ? null : f.title) } }} onClick={() => setExpanded(expanded === f.title ? null : f.title)}
              >
                <div className="row">
                  <span className={`pill sev-${f.severity}`}>{SEVERITY_LABEL[f.severity]}</span>
                  <h3>{f.title}</h3>
                </div>
                <span className="savings">{money(f.value_impact)}</span>
              </div>
              <p className="muted small">{f.category}</p>
              {expanded === f.title && (
                <>
                  <p>{f.description}</p>
                  <p className="muted small">
                    Affected ({f.affected_count}): {f.affected_initiatives.join(', ')}
                    {f.affected_count > f.affected_initiatives.length && ' …'}
                  </p>
                </>
              )}
            </div>
          ))}
        </>
      )}
    </section>
  )
}
