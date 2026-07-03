import { useState } from 'react'
import { getGenome, getMyWork, getPnl, loadSamples, money } from '../api'
import { useEffect } from 'react'
import { getInitiatives } from '../api'
import type { DashboardData, Decision, Initiative, Quadrant, TimelineMonth } from '../types'

type NavTab = 'ideas' | 'command' | 'sources' | 'opportunities' | 'cases' | 'tracking' | 'portfolio'

interface Props {
  data: DashboardData | null
  onNavigate: (tab: NavTab) => void
  onChanged: () => void
}

const QUADRANT_LABELS: Record<string, string> = {
  quick_win: 'Quick wins',
  strategic_bet: 'Strategic bets',
  fill_in: 'Fill-ins',
  deprioritize: 'Deprioritize',
}

const QUADRANT_ORDER: Quadrant[] = ['quick_win', 'strategic_bet', 'fill_in', 'deprioritize']

const ACTION_LABELS: Record<Decision['action'], string> = {
  approve: 'Approve',
  fund: 'Fund',
  verify: 'Verify',
  intervene: 'Intervene',
  review: 'Review',
}

const STAGE_SHORT: Record<string, string> = {
  draft: 'Draft',
  proposed: 'Proposed',
  approved: 'Approved',
  in_delivery: 'Delivery',
  live: 'Live',
  value_realized: 'Realized',
  closed: 'Closed',
}

const compactMoney = (n: number) =>
  n >= 1_000_000 ? `$${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `$${Math.round(n / 1000)}K` : `$${Math.round(n)}`

function ValueOverTime({ months, breakEven }: { months: TimelineMonth[]; breakEven: string | null }) {
  if (months.length < 2) return null
  const W = 920
  const H = 280
  const PAD = { l: 64, r: 110, t: 16, b: 30 }
  const maxY = Math.max(
    ...months.map((m) => Math.max(m.cumulative_cost, m.cumulative_verified, m.cumulative_claimed)),
    1,
  )
  const x = (i: number) => PAD.l + (i / (months.length - 1)) * (W - PAD.l - PAD.r)
  const y = (v: number) => H - PAD.b - (v / maxY) * (H - PAD.t - PAD.b)

  const linePath = (
    key: 'cumulative_cost' | 'cumulative_verified' | 'cumulative_claimed',
    points: { m: TimelineMonth; i: number }[],
  ) =>
    points
      .map(({ m, i }, idx) => `${idx === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(m[key]).toFixed(1)}`)
      .join(' ')

  const indexed = months.map((m, i) => ({ m, i }))
  const actuals = indexed.filter(({ m }) => !m.projected)
  const lastActualIdx = actuals.length ? actuals[actuals.length - 1].i : 0
  const projection = indexed.filter(({ m, i }) => m.projected || i === lastActualIdx)
  const breakEvenIdx = breakEven ? months.findIndex((m) => m.month === breakEven) : -1
  const last = months[months.length - 1]
  const lastActual = months[lastActualIdx]

  const areaPath =
    linePath('cumulative_verified', actuals) +
    ` L${x(lastActualIdx).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`

  return (
    <div className="card chart-card">
      <div className="card-header">
        <h3>Value trajectory</h3>
        <div className="chart-legend muted small">
          <span><i className="swatch sw-verified" /> verified savings</span>
          <span><i className="swatch sw-claimed" /> claimed</span>
          <span><i className="swatch sw-cost" /> invested</span>
          <span><i className="swatch sw-proj" /> projection</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="timeline-chart" role="img">
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(maxY * f)} y2={y(maxY * f)} className="chart-grid" />
            <text x={PAD.l - 8} y={y(maxY * f) + 4} className="chart-tick" textAnchor="end">
              {compactMoney(maxY * f)}
            </text>
          </g>
        ))}
        <path d={areaPath} className="area-verified" />
        <path d={linePath('cumulative_cost', actuals)} className="line line-cost" />
        <path d={linePath('cumulative_claimed', actuals)} className="line line-claimed" />
        <path d={linePath('cumulative_verified', actuals)} className="line line-verified" />
        <path d={linePath('cumulative_verified', projection)} className="line line-verified projected" />
        {breakEvenIdx >= 0 && (
          <g>
            <line x1={x(breakEvenIdx)} x2={x(breakEvenIdx)} y1={PAD.t} y2={H - PAD.b} className="chart-breakeven" />
            <text x={x(breakEvenIdx)} y={PAD.t + 2} className="chart-tick" textAnchor="middle">
              break-even
            </text>
          </g>
        )}
        {/* end-of-line value labels */}
        <text x={x(months.length - 1) + 8} y={y(last.cumulative_verified) + 4} className="chart-label label-verified">
          {compactMoney(last.cumulative_verified)} verified{last.projected ? ' (proj.)' : ''}
        </text>
        <text x={x(lastActualIdx) + 8} y={y(lastActual.cumulative_cost) - 6} className="chart-label label-cost">
          {compactMoney(lastActual.cumulative_cost)} invested
        </text>
        {months.map((m, i) =>
          i % Math.ceil(months.length / 9) === 0 ? (
            <text key={m.month} x={x(i)} y={H - 8} className="chart-tick" textAnchor="middle">
              {m.month.slice(2)}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  )
}

function ValueFlow({ f }: { f: DashboardData['funnel'] }) {
  const W = 640, H = 190, NW = 14, PAD = 26
  const total = Math.max(f.identified_annual_savings, 1)
  const h = (v: number) => Math.max((v / total) * (H - PAD * 2), v > 0 ? 3 : 0)
  const idH = h(f.identified_annual_savings)
  const comH = Math.min(h(f.committed_annual_savings), idH)
  const verH = Math.min(h(f.measured_annual_savings), Math.max(comH, 3))
  const y0 = (H - idH) / 2
  const x1 = 8, x2 = W / 2 - NW / 2, x3 = W - NW - 8
  const ribbon = (xa: number, ya: number, ha: number, xb: number, yb: number, hb: number) => {
    const c = (xa + xb) / 2
    return `M${xa},${ya} C${c},${ya} ${c},${yb} ${xb},${yb} L${xb},${yb + hb} C${c},${yb + hb} ${c},${ya + ha} ${xa},${ya + ha} Z`
  }
  return (
    <div className="value-flow">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Value flowing from identified to committed to verified">
        {idH > comH && (
          <path d={ribbon(x1 + NW, y0 + comH, idH - comH, x2, y0 + comH, Math.max((idH - comH) * 0.2, 2))} className="flow-faded" />
        )}
        <path d={ribbon(x1 + NW, y0, idH, x2, y0, Math.max(comH, 2))} className="flow-committed" />
        {comH > verH && (
          <path d={ribbon(x2 + NW, y0 + verH, comH - verH, x3, y0 + verH, Math.max((comH - verH) * 0.25, 2))} className="flow-pending" />
        )}
        <path d={ribbon(x2 + NW, y0, Math.max(comH, 2), x3, y0, Math.max(verH, 2))} className="flow-verified" />
        <rect x={x1} y={y0} width={NW} height={idH} className="node-identified" rx={4} />
        <rect x={x2} y={y0} width={NW} height={Math.max(comH, 3)} className="node-committed" rx={4} />
        <rect x={x3} y={y0} width={NW} height={Math.max(verH, 3)} className="node-verified" rx={4} />
      </svg>
      <div className="flow-labels">
        <span><strong>{money(f.identified_annual_savings)}</strong><em>identified from data</em></span>
        <span><strong>{money(f.committed_annual_savings)}</strong><em>committed to cases</em></span>
        <span className="flow-verified-label"><strong>{money(f.measured_annual_savings)}</strong><em>verified from evidence</em></span>
      </div>
    </div>
  )
}

function InitiativeRollup() {
  const [initiatives, setInitiatives] = useState<Initiative[]>([])
  useEffect(() => {
    getInitiatives().then((r) => setInitiatives(r.initiatives)).catch(() => {})
  }, [])
  const withActivity = initiatives.filter((i) => i.ideas_count + i.cases_count > 0)
  if (withActivity.length === 0) return null
  const maxValue = Math.max(
    ...withActivity.map((i) =>
      Math.max(i.forecast_annual_savings + i.estimated_idea_benefit, i.verified_annual_savings)),
    1,
  )
  return (
    <div className="card">
      <h3>Value by strategic initiative</h3>
      <p className="muted small">
        Every idea and case rolls up to a leadership objective — proposed value in blue,
        verified value in green.
      </p>
      {withActivity.map((i) => {
        const proposed = i.forecast_annual_savings + i.estimated_idea_benefit
        return (
          <div key={i.id} className="initiative-row">
            <div className="initiative-head">
              <strong>{i.name}</strong>
              <span className="muted small">
                {i.ideas_count} ideas · {i.cases_count} cases
              </span>
            </div>
            <div className="funnel-track">
              <div className="funnel-bar stage-committed" style={{ width: `${(proposed / maxValue) * 100}%` }} />
            </div>
            <div className="funnel-track thin">
              <div className="funnel-bar stage-verified" style={{ width: `${(i.verified_annual_savings / maxValue) * 100}%` }} />
            </div>
            <div className="muted small">
              {money(proposed)}/yr proposed · <span className="savings">{money(i.verified_annual_savings)}/yr verified</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function MyWork({ onNavigate }: { onNavigate: (t: NavTab) => void }) {
  const [items, setItems] = useState<{ kind: string; id: string; title: string; tab: string; age_days: number; what: string }[] | null>(null)
  const who = localStorage.getItem('ivd_user')
  useEffect(() => {
    if (who) getMyWork(who).then((r) => setItems(r.items)).catch(() => setItems([]))
  }, [who])
  if (!who || !items || items.length === 0) return null
  return (
    <div className="card mywork-card">
      <div className="card-header">
        <h3>My work — {who}</h3>
        <span className="muted small">{items.length} item(s) awaiting your action</span>
      </div>
      {items.slice(0, 6).map((w) => (
        <div key={`${w.kind}-${w.id}`} className="decision-row" role="button" tabIndex={0}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNavigate(w.tab as NavTab) } }}
             onClick={() => onNavigate(w.tab as NavTab)}>
          <span className={`pill ${w.kind === 'respond' ? 'act-verify' : 'act-approve'}`}>
            {w.kind === 'respond' ? 'respond' : 'decide'}
          </span>
          <span><strong>{w.title}</strong> <span className="muted small">{w.what}</span></span>
          <span className={`muted small ${w.age_days > 7 ? 'aging-flag' : ''}`}>
            {w.age_days === 0 ? 'today' : `${w.age_days}d`}
          </span>
        </div>
      ))}
    </div>
  )
}

function PnlCard() {
  const [pnl, setPnl] = useState<Awaited<ReturnType<typeof getPnl>> | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => { getPnl().then(setPnl).catch(() => {}) }, [])
  if (!pnl || pnl.capital_deployed === 0) return null
  if (!open) {
    return (
      <div className="card card-header clickable" role="button" tabIndex={0}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(true) } }}
           onClick={() => setOpen(true)}>
        <h3>Innovation P&amp;L</h3>
        <span className="muted small">
          {money(pnl.capital_deployed)} deployed · {money(pnl.verified_annual_return)}/yr verified
        </span>
      </div>
    )
  }
  return (
    <div className="card">
      <div className="card-header clickable" role="button" tabIndex={0}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(false) } }}
           onClick={() => setOpen(false)}>
        <h3>Innovation P&amp;L</h3>
        <span className="muted small">CFO-signable — verified and claimed never blended</span>
      </div>
      <div className="metrics-row">
        <div className="metric"><span className="muted small">Capital deployed (released)</span>
          <strong>{money(pnl.capital_deployed)}</strong></div>
        <div className="metric"><span className="muted small">Verified return /yr</span>
          <strong className="pos">{money(pnl.verified_annual_return)}</strong></div>
        <div className="metric"><span className="muted small">Claimed to date (self-reported)</span>
          <strong>{money(pnl.claimed_savings_to_date)}</strong></div>
        <div className="metric"><span className="muted small">Forecast book (calibrated)</span>
          <strong>{money(pnl.forecast_book_calibrated)}
            <span className="muted small"> of {money(pnl.forecast_book_raw)} raw</span></strong></div>
        <div className="metric"><span className="muted small">Tuition paid (kills)</span>
          <strong>{money(pnl.tuition_paid)}</strong></div>
      </div>
      {pnl.tuition_lessons.length > 0 && (
        <p className="muted small">
          Tuition bought: {pnl.tuition_lessons.filter((t) => t.learning).map((t) => `"${t.learning}"`).join(' · ').slice(0, 220)}…
        </p>
      )}
    </div>
  )
}

function GenomeCard() {
  const [g, setG] = useState<Awaited<ReturnType<typeof getGenome>> | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => { getGenome().then(setG).catch(() => {}) }, [])
  if (!g || g.traits.length === 0) return null
  return (
    <div className="card">
      <div className="card-header clickable" role="button" tabIndex={0}
           onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(!open) } }}
           onClick={() => setOpen(!open)}>
        <h3>Innovation genome</h3>
        <span className="muted small">
          {open ? `what predicts success here, learned from ${g.ideas} ideas`
            : `top trait: ${g.traits[0].trait} (${g.traits[0].multiplier}×)`}
        </span>
      </div>
      {open && g.traits.slice(0, 4).map((t) => (
        <div key={t.trait} className="decision-row">
          <span className={`pill ${t.multiplier >= 1 ? 'act-approve' : 'act-verify'}`}>
            {t.multiplier}×
          </span>
          <span>{t.trait}</span>
          <span className="muted small">n={t.sample}{t.low_confidence ? ' · low confidence' : ''}</span>
        </div>
      ))}
    </div>
  )
}

function DecisionQueue({ decisions, onNavigate }: { decisions: Decision[]; onNavigate: (t: NavTab) => void }) {
  if (decisions.length === 0) return null
  return (
    <div className="card decision-card">
      <h3>Decisions on the table</h3>
      <p className="muted small">
        Ranked by annual value at stake — generated from the current analysis, pipeline, and
        portfolio diagnostic.
      </p>
      {decisions.map((d) => (
        <div key={`${d.action}-${d.title}`} className="decision-row" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onNavigate(d.nav) } }} onClick={() => onNavigate(d.nav)}>
          <span className={`action-chip act-${d.action}`}>{ACTION_LABELS[d.action]}</span>
          <div className="decision-body">
            <strong>{d.title}</strong>
            <div className="muted small">{d.detail}</div>
          </div>
          <div className="decision-value">
            <strong>{money(d.annual_value)}</strong>
            <span className="muted small">/yr at stake</span>
          </div>
          <span className="decision-go">→</span>
        </div>
      ))}
    </div>
  )
}

export default function Dashboard({ data, onNavigate, onChanged }: Props) {
  const [seeding, setSeeding] = useState(false)
  if (!data) {
    return (
      <section aria-busy="true" aria-label="Loading overview">
        <div className="skeleton sk-line" style={{ width: '55%' }} />
        <div className="hero-band">
          {[0, 1, 2, 3].map((i) => <div key={i} className="hero-stat skeleton sk-card" />)}
        </div>
        <div className="card skeleton sk-block" />
        <div className="card skeleton sk-block" style={{ height: 120 }} />
      </section>
    )
  }

  const hasData = data.sources.some((s) => s.rows_loaded > 0)
  if (!hasData) {
    return (
      <section className="first-run">
        <h2>See the hub working in one click</h2>
        <p className="muted">
          Nothing is connected yet. Load the sample dataset to watch the full flow — detected
          opportunities, auto-drafted business cases, and the value funnel — or connect your own
          data sources.
        </p>
        <div className="row first-run-actions">
          <button
            disabled={seeding}
            onClick={async () => {
              setSeeding(true)
              try {
                await loadSamples()
                onChanged()
              } finally {
                setSeeding(false)
              }
            }}
          >
            {seeding ? 'Loading sample data…' : 'Load sample data'}
          </button>
          <button className="secondary" onClick={() => onNavigate('sources')}>
            Connect your data
          </button>
        </div>
        {seeding && (
          <p className="muted small">
            Seeding five sources and running the first automation pass — a few seconds…
          </p>
        )}
      </section>
    )
  }

  const ts = data.timeline.summary
  const f = data.funnel
  const returnMultiple =
    ts && ts.total_invested > 0 ? ts.verified_value_to_date / ts.total_invested : null

  return (
    <section className="exec">
      <div className="section-header">
        <p className="headline-sentence">{data.headline}</p>
        <button className="secondary" onClick={async () => {
          const res = await fetch('/api/reports/board-pack')
          const blob = await res.blob()
          const a = document.createElement('a')
          a.href = URL.createObjectURL(blob)
          a.download = 'board-pack.md'
          a.click()
          URL.revokeObjectURL(a.href)
        }}>Export board pack</button>
      </div>
      <MyWork onNavigate={onNavigate} />
      <PnlCard />

      <div className="hero-band">
        {ts && ts.verified_run_rate > 0 ? (
          <>
            <div className="hero-stat verified">
              <span className="hero-label">Verified savings run-rate</span>
              <strong>{money(ts.verified_run_rate)}<em>/yr</em></strong>
              <span className="muted small">computed from source data, not self-reported</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Invested to date</span>
              <strong>{money(ts.total_invested)}</strong>
              <span className="muted small">implementation cost of live initiatives</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Return to date</span>
              <strong className={returnMultiple != null && returnMultiple >= 1 ? 'pos' : ''}>
                {returnMultiple != null ? `${returnMultiple.toFixed(1)}x` : '—'}
              </strong>
              <span className="muted small">{money(ts.verified_value_to_date)} verified vs. invested</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Break-even</span>
              <strong>{ts.break_even_month ?? '—'}</strong>
              <span className="muted small">
                {ts.break_even_projected ? 'projected at current run-rate' : ts.break_even_month ? 'reached' : 'not yet projectable'}
              </span>
            </div>
          </>
        ) : (
          <>
            <div className="hero-stat verified">
              <span className="hero-label">Opportunity identified</span>
              <strong>{money(f.identified_annual_savings)}<em>/yr</em></strong>
              <span className="muted small">{data.opportunities.count} opportunities across loaded sources</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Risk-adjusted</span>
              <strong>{money(f.risk_adjusted_annual_savings)}</strong>
              <span className="muted small">after confidence and calibration</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Committed</span>
              <strong>{money(f.committed_annual_savings)}</strong>
              <span className="muted small">backed by a business case</span>
            </div>
            <div className="hero-stat">
              <span className="hero-label">Verified</span>
              <strong>{money(f.measured_annual_savings)}</strong>
              <span className="muted small">proven from data</span>
            </div>
          </>
        )}
        {data.portfolio_health != null && (
          <div className="hero-stat">
            <span className="hero-label">Portfolio health</span>
            <span className="gauge-wrap">
              <svg viewBox="0 0 42 42" className="gauge" aria-hidden="true">
                <circle className="gauge-bg" cx="21" cy="21" r="16" pathLength={100} />
                <circle
                  className={`gauge-fg ${data.portfolio_health >= 70 ? 'g-good' : data.portfolio_health >= 40 ? 'g-warn' : 'g-bad'}`}
                  cx="21" cy="21" r="16" pathLength={100}
                  strokeDasharray={`${data.portfolio_health} 100`}
                />
              </svg>
              <strong className={data.portfolio_health >= 70 ? 'pos' : data.portfolio_health >= 40 ? 'warn' : 'neg'}>
                {data.portfolio_health}<em>/100</em>
              </strong>
            </span>
            <span className="muted small">existing initiative portfolio</span>
          </div>
        )}
      </div>

      <DecisionQueue decisions={data.decisions} onNavigate={onNavigate} />

      <InitiativeRollup />

      <div className="card hub-strip">
        <div className="hub-pipeline">
          <span className="hero-label">Innovation pipeline</span>
          <div className="row">
            {Object.entries(data.hub.pipeline_stages)
              .filter(([stage]) => stage !== 'closed')
              .map(([stage, count]) => (
                <button
                  key={stage}
                  className="chip"
                  onClick={() => onNavigate('command')}
                  title="Open the command center"
                >
                  {STAGE_SHORT[stage]} <strong>{count}</strong>
                </button>
              ))}
            <button className="chip" onClick={() => onNavigate('ideas')}>
              Ideas <strong>{data.hub.ideas.total}</strong>
            </button>
          </div>
        </div>
        <div className="hub-facts muted small">
          <span>
            <strong>Automation:</strong>{' '}
            {Object.entries(data.hub.automation.actions_by_rule).length > 0
              ? Object.entries(data.hub.automation.actions_by_rule)
                  .map(([rule, n]) => `${rule.replace('_', ' ')} ×${n}`)
                  .join(' · ')
              : 'no actions yet'}
            {data.hub.automation.last_run && ` · last run ${data.hub.automation.last_run.slice(0, 16).replace('T', ' ')}`}
          </span>
          <span>
            <strong>Experiments:</strong>{' '}
            {data.hub.experiments.concluded + data.hub.experiments.running === 0
              ? 'none yet'
              : `${data.hub.experiments.running} running · ${data.hub.experiments.concluded} concluded` +
                (data.hub.experiments.kill_rate != null
                  ? ` · ${Math.round(data.hub.experiments.kill_rate * 100)}% kill rate (healthy portfolios kill 40–60%)`
                  : '')}
          </span>
          <span>
            <strong>Time to value:</strong>{' '}
            {data.hub.time_to_value.median_days_to_live != null
              ? `${data.hub.time_to_value.median_days_to_live}d to live`
              : 'no cases live yet'}
            {data.hub.time_to_value.median_days_live_to_evidence != null &&
              ` · ${data.hub.time_to_value.median_days_live_to_evidence}d live → first evidence`}
          </span>
        </div>
      </div>

      {ts && <ValueOverTime months={data.timeline.months} breakEven={ts.break_even_month} />}

      <div className="dash-grid">
        <div className="card">
          <h3>Value conversion</h3>
          <p className="muted small">
            How identified opportunity converts to verified value — each stage is a harder
            standard of proof.
          </p>
          <ValueFlow f={f} />
          <p className="muted small">
            {f.identified_annual_savings > 0 && f.measured_annual_savings > 0
              ? `${Math.round((f.measured_annual_savings / f.identified_annual_savings) * 100)}% of identified value is now verified.`
              : 'Verified value appears here once implemented work is measured against its frozen baseline.'}
          </p>

          <h3 className="spaced">Horizon balance <span className="muted small">vs 70/20/10 target</span></h3>
          {(['h1', 'h2', 'h3'] as const).map((h) => {
            const bucket = data.hub.horizon_mix[h]
            if (!bucket) return null
            const share = bucket.share != null ? Math.round(bucket.share * 100) : null
            const target = bucket.target_share != null ? Math.round(bucket.target_share * 100) : null
            return (
              <div key={h} className="funnel-row">
                <span className="funnel-label">
                  {h.toUpperCase()} {h === 'h1' ? 'core' : h === 'h2' ? 'adjacent' : 'transform'}
                </span>
                <div className="funnel-track">
                  <div
                    className={`funnel-bar ${h === 'h1' ? 'stage-identified' : h === 'h2' ? 'stage-committed' : 'mix-strategic_bet'}`}
                    style={{ width: `${share ?? 0}%` }}
                  />
                </div>
                <span className="funnel-value">
                  {share != null ? `${share}%` : '—'} <span className="muted">/ {target}%</span>
                </span>
              </div>
            )
          })}
          {Object.values(data.hub.horizon_mix).every((b) => !b.count) ? null : (
            (data.hub.horizon_mix.h2?.count ?? 0) + (data.hub.horizon_mix.h3?.count ?? 0) === 0 && (
              <p className="muted small">
                Portfolio is 100% Horizon-1 cost work — launch a challenge for growth or
                experience ideas to balance it.
              </p>
            )
          )}

          <h3 className="spaced">Where the next value is</h3>
          {QUADRANT_ORDER.map((q) => {
            const bucket = data.opportunities.quadrants[q]
            if (!bucket) return null
            const maxVal = Math.max(...Object.values(data.opportunities.quadrants).map((b) => b.value), 1)
            return (
              <div key={q} className="funnel-row">
                <span className="funnel-label">{QUADRANT_LABELS[q]}</span>
                <div className="funnel-track">
                  <div className={`funnel-bar mix-${q}`} style={{ width: `${(bucket.value / maxVal) * 100}%` }} />
                </div>
                <span className="funnel-value">{bucket.count} · {money(bucket.value)}</span>
              </div>
            )
          })}
        </div>

        <div className="card">
          <h3>Confidence in these numbers</h3>
          <ul className="confidence-list">
            <li>
              <strong>Verified ≠ claimed.</strong> {money(f.measured_annual_savings)}/yr is computed
              from source data against frozen baselines; {money(f.claimed_savings_to_date)} of
              self-reported savings is tracked separately and never blended in.
            </li>
            <li>
              <strong>Estimates are calibrated.</strong>{' '}
              {data.calibration.cases_observed > 0
                ? `Forecasts are corrected by realization rates measured on ${data.calibration.cases_observed} completed case${data.calibration.cases_observed > 1 ? 's' : ''}.`
                : 'Realization rates will automatically correct forecasts as implemented cases report actuals.'}
            </li>
            <li>
              <strong>Soft claims are flagged.</strong> Business-case claims that no data source
              can verify are listed on each case, not silently counted.
            </li>
          </ul>
          {Object.keys(data.calibration.categories).length > 0 && (
            <table className="kpi-table">
              <thead>
                <tr><th>Category</th><th className="num">Forecast</th><th className="num">Actual</th><th className="num">Realized</th></tr>
              </thead>
              <tbody>
                {Object.entries(data.calibration.categories).map(([cat, s]) => (
                  <tr key={cat}>
                    <td>{cat}</td>
                    <td className="num">{money(s.forecast_annual_savings)}</td>
                    <td className="num">{money(s.actual_annual_savings)}</td>
                    <td className={`num ${s.realization_rate >= 1 ? 'pos' : 'neg'}`}>
                      {Math.round(s.realization_rate * 100)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h3 className="spaced">Delivery pipeline</h3>
          {data.pipeline.length === 0 ? (
            <p className="muted small">No business cases yet — the decision queue above suggests where to start.</p>
          ) : (
            <table className="kpi-table">
              <thead>
                <tr><th>Case</th><th>Status</th><th className="num">Forecast /yr</th><th className="num">Verified /yr</th></tr>
              </thead>
              <tbody>
                {data.pipeline.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.title}</strong></td>
                    <td>
                      <span className={p.status === 'implemented' ? 'badge badge-ok' : 'badge'}>{p.status}</span>
                    </td>
                    <td className="num">{p.forecast_annual_savings != null ? money(p.forecast_annual_savings) : '—'}</td>
                    <td className="num savings">{p.measured_annual_savings ? money(p.measured_annual_savings) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="source-strip muted small">
        Data:{' '}
        {data.sources.map((s) => (
          <span key={s.source_type} className="badge">
            {s.source_type.toUpperCase()}{' '}
            {s.rows_loaded > 0 ? `${s.rows_loaded} rows · ${s.updated_at?.slice(0, 10) ?? ''}` : 'not loaded'}
          </span>
        ))}
        <button className="linklike" onClick={() => onNavigate('sources')}>manage sources →</button>
      </div>
      <GenomeCard />
    </section>
  )
}
