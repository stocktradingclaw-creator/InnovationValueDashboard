import { useRef, useState } from 'react'
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
          <h2>Portfolio value diagnostic</h2>
          <p className="muted">
            Ingest an existing initiative portfolio (PMO export) and find where it leaks value —
            unverified claims, realization shortfalls, weak ROI, stalled and parked work.
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
      <Simulator />

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
