import { useMemo, useState } from 'react'
import { money } from '../api'
import type { Opportunity, PrioritizationSummary, Quadrant, Weights } from '../types'

interface Props {
  opportunities: Opportunity[]
  total: number
  summary: PrioritizationSummary | null
  weights: Weights
  onWeightsChange: (w: Weights) => void
  hasData: boolean
}

const SOURCE_LABELS: Record<string, string> = {
  cmdb: 'CMDB',
  erp: 'ERP',
  cloud: 'Cloud',
  itsm: 'ITSM',
}

const QUADRANT_LABELS: Record<Quadrant, string> = {
  quick_win: 'Quick win',
  strategic_bet: 'Strategic bet',
  fill_in: 'Fill-in',
  deprioritize: 'Deprioritize',
}

function WeightSliders({ weights, onChange }: { weights: Weights; onChange: (w: Weights) => void }) {
  const total = weights.value + weights.efficiency + weights.speed || 1
  const rows: { key: keyof Weights; label: string; hint: string }[] = [
    { key: 'value', label: 'Value', hint: 'size of prize (risk-adjusted savings)' },
    { key: 'efficiency', label: 'Efficiency', hint: 'payback ratio (savings vs. cost)' },
    { key: 'speed', label: 'Speed', hint: 'time to value' },
  ]
  return (
    <div className="card weights-card">
      <h3>Scoring weights</h3>
      {rows.map(({ key, label, hint }) => (
        <div key={key} className="weight-row">
          <span className="weight-label">
            {label} <span className="muted small">{hint}</span>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            value={weights[key]}
            onChange={(e) => onChange({ ...weights, [key]: Number(e.target.value) })}
          />
          <span className="weight-pct">{Math.round((weights[key] / total) * 100)}%</span>
        </div>
      ))}
    </div>
  )
}

function QuadrantMatrix({ opportunities }: { opportunities: Opportunity[] }) {
  // Position dots by percentile so the median split lands exactly on the
  // quadrant lines, matching how quadrants are assigned server-side.
  const dots = useMemo(() => {
    const byCost = [...opportunities].sort(
      (a, b) => a.priority.est_implementation_cost - b.priority.est_implementation_cost,
    )
    const byValue = [...opportunities].sort(
      (a, b) => a.priority.risk_adjusted_annual_savings - b.priority.risk_adjusted_annual_savings,
    )
    const n = Math.max(opportunities.length - 1, 1)
    return opportunities.map((o) => ({
      o,
      x: (byCost.indexOf(o) / n) * 90 + 5,
      y: 95 - (byValue.indexOf(o) / n) * 90,
    }))
  }, [opportunities])

  return (
    <div className="card matrix-card">
      <h3>Value vs. effort</h3>
      <div className="matrix">
        <span className="matrix-corner tl">Quick wins</span>
        <span className="matrix-corner tr">Strategic bets</span>
        <span className="matrix-corner bl">Fill-ins</span>
        <span className="matrix-corner br">Deprioritize</span>
        {dots.map(({ o, x, y }) => (
          <span
            key={o.id}
            className={`dot dot-${o.priority.quadrant}`}
            style={{ left: `${x}%`, top: `${y}%` }}
            title={`${o.title}\nscore ${o.priority.score} · ${money(
              o.priority.risk_adjusted_annual_savings,
            )}/yr risk-adj · ~${money(o.priority.est_implementation_cost)} to implement`}
          />
        ))}
      </div>
      <div className="matrix-axes muted small">
        <span>← cheaper to implement</span>
        <span>more expensive →</span>
      </div>
    </div>
  )
}

export default function Opportunities({
  opportunities,
  total,
  summary,
  weights,
  onWeightsChange,
  hasData,
}: Props) {
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<string | null>(null)

  if (!hasData) {
    return (
      <section>
        <h2>Prioritized opportunities</h2>
        <p className="muted">
          No data loaded yet. Go to <strong>Data Sources</strong> and upload customer exports,
          sync a live connector, or load the sample data.
        </p>
      </section>
    )
  }

  const filtered =
    sourceFilter === 'all'
      ? opportunities
      : opportunities.filter((o) => o.source === sourceFilter)

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Prioritized opportunities</h2>
          <p className="muted">
            {opportunities.length} opportunities, ranked by weighted score — not raw savings.
            {summary && (
              <>
                {' '}Top <strong>{summary.count_for_80_pct_of_value}</strong> capture 80% of the{' '}
                {money(summary.total_risk_adjusted_annual_savings)}/yr risk-adjusted value.
              </>
            )}
          </p>
        </div>
        <div className="total-banner">
          <span className="muted">Total identified</span>
          <strong>{money(total)}/yr</strong>
        </div>
      </div>

      <div className="prioritization-panel">
        <WeightSliders weights={weights} onChange={onWeightsChange} />
        <QuadrantMatrix opportunities={opportunities} />
      </div>

      <div className="row filter-row">
        {['all', 'cmdb', 'erp', 'cloud', 'itsm'].map((s) => (
          <button
            key={s}
            className={sourceFilter === s ? 'chip chip-active' : 'chip'}
            onClick={() => setSourceFilter(s)}
          >
            {s === 'all' ? 'All sources' : SOURCE_LABELS[s]}
          </button>
        ))}
      </div>

      <table className="opps-table">
        <thead>
          <tr>
            <th className="num">#</th>
            <th className="num">Score</th>
            <th>Opportunity</th>
            <th className="num">Est. savings/yr</th>
            <th className="num">Payback</th>
            <th>Quadrant</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((o) => (
            <>
              <tr
                key={o.id}
                className="opp-row"
                onClick={() => setExpanded(expanded === o.id ? null : o.id)}
              >
                <td className="num muted">{o.priority.rank}</td>
                <td className="num">
                  <strong>{o.priority.score}</strong>
                </td>
                <td>
                  <span className={`tag tag-${o.source}`}>{SOURCE_LABELS[o.source]}</span>{' '}
                  <strong>{o.title}</strong>
                  <div className="muted small">{o.category}</div>
                </td>
                <td className="num savings">{money(o.estimated_annual_savings)}</td>
                <td className="num">
                  {o.priority.payback_months != null ? `${o.priority.payback_months} mo` : '—'}
                </td>
                <td>
                  <span className={`pill quad-${o.priority.quadrant}`}>
                    {QUADRANT_LABELS[o.priority.quadrant]}
                  </span>
                </td>
              </tr>
              {expanded === o.id && (
                <tr key={`${o.id}-detail`} className="detail-row">
                  <td colSpan={6}>
                    <p>{o.description}</p>
                    <div className="metrics-row">
                      <div className="metric">
                        <span className="muted small">Risk-adjusted/yr</span>
                        <strong>{money(o.priority.risk_adjusted_annual_savings)}</strong>
                      </div>
                      <div className="metric">
                        <span className="muted small">Est. cost to implement</span>
                        <strong>{money(o.priority.est_implementation_cost)}</strong>
                      </div>
                      <div className="metric">
                        <span className="muted small">Time to value</span>
                        <strong>{o.priority.time_to_value_months} mo</strong>
                      </div>
                      <div className="metric">
                        <span className="muted small">1-yr net</span>
                        <strong className={o.priority.first_year_net >= 0 ? 'pos' : 'neg'}>
                          {money(o.priority.first_year_net)}
                        </strong>
                      </div>
                      <div className="metric">
                        <span className="muted small">3-yr net</span>
                        <strong className={o.priority.three_year_net >= 0 ? 'pos' : 'neg'}>
                          {money(o.priority.three_year_net)}
                        </strong>
                      </div>
                    </div>
                    <p className="muted small">
                      Score components — value {o.priority.components.value} · efficiency{' '}
                      {o.priority.components.efficiency} · speed {o.priority.components.speed} ·
                      effort <span className={`pill pill-${o.effort}`}>{o.effort}</span> ·
                      confidence <span className={`pill pill-${o.confidence}`}>{o.confidence}</span>
                    </p>
                    <p className="muted small">
                      Affected ({o.affected_count}): {o.affected_items.join(', ')}
                      {o.affected_count > o.affected_items.length && ' …'}
                    </p>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </section>
  )
}
