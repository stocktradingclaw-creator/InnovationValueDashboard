import { useEffect, useState } from 'react'
import { getPipeline, money } from '../api'
import type { PipelineData } from '../types'

const STAGE_LABELS: Record<string, string> = {
  proposed: 'Proposed',
  qualified: 'Qualified',
  prioritized: 'Prioritized',
  draft: 'Draft case',
  experiment: 'Experiment',
  approved: 'Approved',
  in_delivery: 'In delivery',
  live: 'Live',
  value_realized: 'Value realized',
  scale: 'Scale',
}

export default function PipelineView() {
  const [data, setData] = useState<PipelineData | null>(null)

  useEffect(() => {
    getPipeline().then(setData).catch(() => {})
  }, [])

  if (!data) return <section><p className="muted">Loading the pipeline…</p></section>

  const t = data.totals
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Innovation pipeline</h2>
          <p className="muted">
            Where every opportunity sits across the lifecycle — gate conversion, time in stage,
            and value at each step. Items idle longer than {data.aging_threshold_days} days are
            flagged.
          </p>
        </div>
      </div>

      <div className="metrics-row headline-row">
        <div className="metric headline">
          <span className="hero-label">In flight</span>
          <strong>{t.in_flight}</strong>
          <span className="muted small">ideas + cases, excluding terminal</span>
        </div>
        <div className="metric headline">
          <span className="hero-label">Pipeline value</span>
          <strong>{money(t.pipeline_value)}<em>/yr</em></strong>
          <span className="muted small">estimated, pre-verification</span>
        </div>
        <div className="metric headline verified">
          <span className="hero-label">Verified value</span>
          <strong>{money(t.verified_value)}<em>/yr</em></strong>
          <span className="muted small">measured from source data</span>
        </div>
        <div className="metric headline">
          <span className="hero-label">Idea → case conversion</span>
          <strong>{t.end_to_end_conversion != null ? `${Math.round(t.end_to_end_conversion * 100)}%` : '—'}</strong>
          <span className="muted small">of all ideas ever submitted</span>
        </div>
      </div>

      {data.phases.map((phase) => (
        <div key={phase.phase} className="phase-band">
          <h3 className="phase-title">{phase.phase}</h3>
          <div className="pipeline-board">
            {phase.stages.map((s) => (
              <div key={s.stage} className="pipeline-col">
                <div className="pipeline-col-head">
                  <strong>{STAGE_LABELS[s.stage] ?? s.stage}</strong>
                  <span className="muted small">
                    {s.count} · {money(s.value)}/yr
                    {s.verified > 0 && <> · <span className="savings">{money(s.verified)} verified</span></>}
                  </span>
                  <span className="muted small">
                    {s.conversion_from_previous != null && `${Math.round(s.conversion_from_previous * 100)}% pass gate`}
                    {s.median_dwell_days != null && ` · ~${s.median_dwell_days}d dwell`}
                  </span>
                  {s.aging > 0 && (
                    <span className="pill act-verify">{s.aging} aging &gt;{data.aging_threshold_days}d</span>
                  )}
                </div>
                {s.items.map((item) => (
                  <div key={item.id} className="pipeline-item">
                    <div className="small"><strong>{item.title}</strong></div>
                    <div className="muted small">
                      {item.value > 0 ? `${money(item.value)}/yr` : 'unsized'}
                      {item.owner ? ` · ${item.owner}` : ''}
                      {item.days_in_stage != null && (
                        <span className={item.days_in_stage > data.aging_threshold_days ? ' aging-flag' : ''}>
                          {' '}· {item.days_in_stage}d here
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      ))}

      <p className="muted small">
        Exited the pipeline: {data.terminal.backlog} on the backlog · {data.terminal.declined} declined ·{' '}
        {data.terminal.closed} closed or killed after experiments.
      </p>
    </section>
  )
}
