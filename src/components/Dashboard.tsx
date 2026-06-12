import { money } from '../api'
import type { DashboardData, Quadrant } from '../types'

interface Props {
  data: DashboardData | null
  onNavigate: (tab: 'sources' | 'opportunities' | 'cases' | 'tracking') => void
}

const QUADRANT_LABELS: Record<string, string> = {
  quick_win: 'Quick wins',
  strategic_bet: 'Strategic bets',
  fill_in: 'Fill-ins',
  deprioritize: 'Deprioritize',
}

const QUADRANT_ORDER: Quadrant[] = ['quick_win', 'strategic_bet', 'fill_in', 'deprioritize']

function Funnel({ data }: { data: DashboardData }) {
  const f = data.funnel
  const max = Math.max(f.identified_annual_savings, 1)
  const stages = [
    {
      label: 'Identified',
      value: f.identified_annual_savings,
      hint: 'headline estimate across all detected opportunities',
      cls: 'stage-identified',
    },
    {
      label: 'Risk-adjusted',
      value: f.risk_adjusted_annual_savings,
      hint: 'after detection confidence and learned realization rates',
      cls: 'stage-adjusted',
    },
    {
      label: 'Committed',
      value: f.committed_annual_savings,
      hint: 'opportunities with a business case behind them',
      cls: 'stage-committed',
    },
    {
      label: 'Verified',
      value: f.measured_annual_savings,
      hint: 'measured from data via frozen-baseline metric bindings',
      cls: 'stage-verified',
    },
  ]
  return (
    <div className="card">
      <h3>Value funnel <span className="muted small">annual run-rate</span></h3>
      {stages.map((s) => (
        <div key={s.label} className="funnel-row">
          <span className="funnel-label">{s.label}</span>
          <div className="funnel-track">
            <div
              className={`funnel-bar ${s.cls}`}
              style={{ width: `${Math.max((s.value / max) * 100, s.value > 0 ? 2 : 0)}%` }}
            />
          </div>
          <span className="funnel-value">{money(s.value)}</span>
          <span className="muted small funnel-hint">{s.hint}</span>
        </div>
      ))}
      {f.claimed_savings_to_date > 0 && (
        <p className="muted small">
          Plus {money(f.claimed_savings_to_date)} claimed savings to date (self-reported — kept
          separate from verified).
        </p>
      )}
    </div>
  )
}

export default function Dashboard({ data, onNavigate }: Props) {
  if (!data) return <section><p className="muted">Loading…</p></section>

  const hasData = data.sources.some((s) => s.rows_loaded > 0)
  if (!hasData) {
    return (
      <section>
        <h2>Overview</h2>
        <p className="muted">
          No customer data loaded yet. Start in{' '}
          <button className="linklike" onClick={() => onNavigate('sources')}>
            Data Sources
          </button>{' '}
          — upload exports, sync a connector, or load the sample data.
        </p>
      </section>
    )
  }

  const implemented = data.pipeline.filter((p) => p.status === 'implemented')
  const calCategories = Object.entries(data.calibration.categories)

  return (
    <section>
      <div className="metrics-row headline-row">
        <div className="metric headline">
          <span className="muted small">Identified /yr</span>
          <strong>{money(data.funnel.identified_annual_savings)}</strong>
        </div>
        <div className="metric headline">
          <span className="muted small">Risk-adjusted /yr</span>
          <strong>{money(data.funnel.risk_adjusted_annual_savings)}</strong>
        </div>
        <div className="metric headline">
          <span className="muted small">Committed /yr</span>
          <strong>{money(data.funnel.committed_annual_savings)}</strong>
        </div>
        <div className="metric headline verified">
          <span className="muted small">Verified /yr</span>
          <strong>{money(data.funnel.measured_annual_savings)}</strong>
        </div>
        <div className="metric headline">
          <span className="muted small">Opportunities</span>
          <strong>{data.opportunities.count}</strong>
        </div>
      </div>

      <Funnel data={data} />

      <div className="dash-grid">
        <div className="card">
          <h3>
            Top opportunities{' '}
            <button className="linklike small" onClick={() => onNavigate('opportunities')}>
              view all →
            </button>
          </h3>
          <p className="muted small">
            Top {data.opportunities.count_for_80_pct_of_value} capture 80% of risk-adjusted value.
          </p>
          {data.opportunities.top.map((o, i) => (
            <div key={o.id} className="top-opp">
              <span className="muted">{i + 1}.</span>
              <div className="top-opp-body">
                <strong>{o.title}</strong>
                <div className="row">
                  <span className={`pill quad-${o.quadrant}`}>{QUADRANT_LABELS[o.quadrant]}</span>
                  <span className="muted small">score {o.score}</span>
                  <span className="savings small">{money(o.estimated_annual_savings)}/yr</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="card">
          <h3>Portfolio mix</h3>
          {QUADRANT_ORDER.map((q) => {
            const bucket = data.opportunities.quadrants[q]
            if (!bucket) return null
            const maxVal = Math.max(
              ...Object.values(data.opportunities.quadrants).map((b) => b.value), 1,
            )
            return (
              <div key={q} className="funnel-row">
                <span className="funnel-label">{QUADRANT_LABELS[q]}</span>
                <div className="funnel-track">
                  <div
                    className={`funnel-bar mix-${q}`}
                    style={{ width: `${(bucket.value / maxVal) * 100}%` }}
                  />
                </div>
                <span className="funnel-value">
                  {bucket.count} · {money(bucket.value)}
                </span>
              </div>
            )
          })}

          <h3 className="spaced">
            Estimate calibration{' '}
            <span className="muted small">({data.calibration.cases_observed} cases observed)</span>
          </h3>
          {calCategories.length === 0 ? (
            <p className="muted small">
              No implemented cases with actuals yet — forecasts are taken at face value. As
              tracking data lands, realization rates will discount or boost each category
              automatically.
            </p>
          ) : (
            <table className="kpi-table">
              <thead>
                <tr><th>Category</th><th className="num">Forecast</th><th className="num">Actual</th><th className="num">Realization</th></tr>
              </thead>
              <tbody>
                {calCategories.map(([cat, s]) => (
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
        </div>
      </div>

      <div className="dash-grid">
        <div className="card">
          <h3>
            Case pipeline{' '}
            <button className="linklike small" onClick={() => onNavigate('tracking')}>
              tracking →
            </button>
          </h3>
          {data.pipeline.length === 0 ? (
            <p className="muted small">
              No business cases yet — link one to a top opportunity to start the value record.
            </p>
          ) : (
            <table className="kpi-table">
              <thead>
                <tr>
                  <th>Case</th><th>Status</th><th className="num">Forecast /yr</th>
                  <th className="num">Verified /yr</th><th className="num">Payback</th>
                </tr>
              </thead>
              <tbody>
                {data.pipeline.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.title}</strong></td>
                    <td>
                      <span className={p.status === 'implemented' ? 'badge badge-ok' : 'badge'}>
                        {p.status}
                      </span>
                    </td>
                    <td className="num">
                      {p.forecast_annual_savings != null ? money(p.forecast_annual_savings) : '—'}
                    </td>
                    <td className="num savings">
                      {p.measured_annual_savings ? money(p.measured_annual_savings) : '—'}
                    </td>
                    <td className="num">
                      {p.payback_progress_pct != null ? (
                        <div className="progress inline-progress" title={`${p.payback_progress_pct}%`}>
                          <div className="progress-bar" style={{ width: `${p.payback_progress_pct}%` }} />
                        </div>
                      ) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {implemented.length > 0 && (
            <p className="muted small">
              {implemented.length} implemented · verified value updates when datasets are
              refreshed and bindings re-observed.
            </p>
          )}
        </div>

        <div className="card">
          <h3>
            Data freshness{' '}
            <button className="linklike small" onClick={() => onNavigate('sources')}>
              sources →
            </button>
          </h3>
          <table className="kpi-table">
            <thead>
              <tr><th>Source</th><th className="num">Rows</th><th>Origin</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {data.sources.map((s) => (
                <tr key={s.source_type}>
                  <td>{s.source_type.toUpperCase()}</td>
                  <td className="num">{s.rows_loaded || '—'}</td>
                  <td className="muted">{s.origin ?? '—'}</td>
                  <td className="muted small">
                    {s.updated_at ? s.updated_at.slice(0, 10) : 'never'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            Verified value is only as fresh as the data behind it — re-sync connectors before
            re-observing bindings.
          </p>
        </div>
      </div>
    </section>
  )
}
