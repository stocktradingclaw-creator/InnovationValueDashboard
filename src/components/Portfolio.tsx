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

interface Telemetry {
  strategy_context: { ambition: string; disruption_current: number; susceptibility: number; target_onn: Record<string, number> }
  balance: { rows: { horizon: string; share: number; target: number; spend: number; count: number; variance: number }[]; drift_alert: boolean; total_spend: number }
  funnel: { stages: Record<string, number>; killed: number; conversions: { from: string; to: string; rate: number | null }[]; purgatory: { id: string; title: string; days: number }[]; purgatory_threshold_days: number }
  funding: { committed: number; released: number; gate_queue: { case_id: string; title: string; tranche: string; amount: number; milestone: string; overdue: boolean }[]; kills_by_stage: Record<string, number>; kill_note: string }
  value: { pools: { name: string; low: number; high: number; assumptions: string; gaps_value_low: number; gaps_value_high: number; gap_names: string[] }[]; trapped_low: number; trapped_high: number; invested: number; realized_claimed: number; realized_verified: number; achievement_gap: number }
  digital_core: { score: number | null; weak_dimensions: string[]; scaling_at_risk: { id: string; title: string }[] }
}

export function TelemetryPanels() {
  const [t, setT] = useState<Telemetry | null>(null)
  useEffect(() => { fetch('/api/portfolio/telemetry').then((r) => r.json()).then(setT).catch(() => {}) }, [])
  if (!t) return null
  const ONN_LABEL: Record<string, string> = { old: 'Old — transform the core', now: 'Now — grow current business', new: 'New — scale future bets' }
  const FUNNEL_ORDER = ['idea', 'validated', 'pilot', 'scaling', 'scaled']
  const maxStage = Math.max(...FUNNEL_ORDER.map((f) => t.funnel.stages[f] ?? 0), 1)
  return (
    <>
      <div className="card">
        <div className="card-header">
          <h3>Portfolio balance — old / now / new</h3>
          {t.balance.drift_alert && <span className="pill act-verify">drift vs target</span>}
        </div>
        {t.balance.rows.map((b) => (
          <div key={b.horizon} className="initiative-row">
            <div className="initiative-head">
              <strong>{ONN_LABEL[b.horizon]}</strong>
              <span className="muted small">{b.count} initiative(s) · {money(b.spend)} released ·{' '}
                {Math.round(b.share * 100)}% vs {Math.round(b.target * 100)}% target
                {Math.abs(b.variance) > 0.15 ? ' ⚠' : ''}</span>
            </div>
            <div className="funnel-track"><div className="funnel-bar stage-committed" style={{ width: `${b.share * 100}%` }} /></div>
            <div className="funnel-track thin"><div className="funnel-bar stage-verified" style={{ width: `${b.target * 100}%` }} /></div>
          </div>
        ))}
        <p className="muted small">Classified by horizon and benefit heuristics; target set in
          Hub Settings → Strategy context.</p>
      </div>

      <div className="card">
        <h3>Funnel &amp; scaling</h3>
        <div className="row" style={{ alignItems: 'flex-end', gap: '0.4rem' }}>
          {FUNNEL_ORDER.map((f, i) => (
            <div key={f} style={{ flex: 1, textAlign: 'center' }}>
              <div className="funnel-bar stage-committed" style={{
                height: 8 + ((t.funnel.stages[f] ?? 0) / maxStage) * 60, borderRadius: 6 }} />
              <span className="small"><strong>{t.funnel.stages[f] ?? 0}</strong> {f}</span>
              {i < 4 && <div className="muted small">→ {t.funnel.conversions[i]?.rate != null
                ? `${Math.round((t.funnel.conversions[i].rate ?? 0) * 100)}%` : '—'}</div>}
            </div>
          ))}
          <div style={{ textAlign: 'center' }}>
            <span className="pill act-intervene">{t.funnel.killed} killed</span>
            <div className="muted small">{t.funding.kill_note}</div>
          </div>
        </div>
        {t.funnel.purgatory.length > 0 && (
          <p className="small pending-action">PoC purgatory ({'>'}{t.funnel.purgatory_threshold_days}d in pilot):{' '}
            {t.funnel.purgatory.map((p0) => `${p0.title} (${p0.days}d)`).join(' · ')}</p>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Gate reviews &amp; funding</h3>
          <span className="muted small">{money(t.funding.released)} released of {money(t.funding.committed)} committed</span>
        </div>
        {t.funding.gate_queue.length === 0 && <p className="muted small">No pending gate decisions.</p>}
        {t.funding.gate_queue.map((g) => (
          <div key={`${g.case_id}-${g.tranche}`} className="decision-row">
            <span className={`pill ${g.overdue ? 'act-intervene' : 'act-verify'}`}>{g.overdue ? 'overdue' : 'upcoming'}</span>
            <span><strong>{g.title}</strong> <span className="muted small">{g.tranche} · {money(g.amount)} · gate: {g.milestone}</span></span>
          </div>
        ))}
        {Object.keys(t.funding.kills_by_stage).length > 0 && (
          <p className="muted small">Kills by stage: {Object.entries(t.funding.kills_by_stage)
            .map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Trapped value → realization</h3>
          <span className="muted small">one roll-up: pool → gap → initiative → realized</span>
        </div>
        <div className="metrics-row">
          <div className="metric"><span className="muted small">Trapped value (range)</span>
            <strong>{money(t.value.trapped_low)} – {money(t.value.trapped_high)}</strong></div>
          <div className="metric"><span className="muted small">Invested (released)</span>
            <strong>{money(t.value.invested)}</strong></div>
          <div className="metric"><span className="muted small">Realized (claimed + verified)</span>
            <strong className="pos">{money(t.value.realized_claimed + t.value.realized_verified)}</strong></div>
          <div className="metric"><span className="muted small">Achievement gap</span>
            <strong className={t.value.achievement_gap > 0 ? 'neg' : 'pos'}>{money(t.value.achievement_gap)}</strong></div>
        </div>
        {t.value.pools.map((p0) => (
          <div key={p0.name} className="decision-row">
            <span className="pill act-approve">{money(p0.low)}–{money(p0.high)}</span>
            <span><strong>{p0.name}</strong>{' '}
              <span className="muted small">{p0.assumptions} · linked gaps: {p0.gap_names.join(', ') || 'none sized yet'}
                {p0.gaps_value_high > 0 ? ` (${money(p0.gaps_value_low)}–${money(p0.gaps_value_high)})` : ''}</span></span>
          </div>
        ))}
        {t.digital_core.score != null && (
          <p className="small pending-action">Digital-core readiness: <strong>{t.digital_core.score}/5</strong>
            {t.digital_core.weak_dimensions.length > 0 &&
              <> — scaling gated by: {t.digital_core.weak_dimensions.join(', ')}
                {t.digital_core.scaling_at_risk.length > 0 && ` (${t.digital_core.scaling_at_risk.length} initiative(s) at risk)`}</>}
          </p>
        )}
      </div>
    </>
  )
}

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
      <TelemetryPanels />
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
