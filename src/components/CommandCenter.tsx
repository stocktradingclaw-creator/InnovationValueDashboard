import { useEffect, useState } from 'react'
import {
  decide, getCommandQueue, getScoringConfig, money,
  putGovernance, putScoringConfig, runAutomation,
} from '../api'
import type { BusinessCase, CommandQueue, Idea, ScoringConfig, Stage } from '../types'

interface Props {
  onChanged: () => void
}

const STAGE_LABELS: Record<Stage, string> = {
  draft: 'Draft',
  proposed: 'Proposed',
  approved: 'Approved',
  in_delivery: 'In delivery',
  live: 'Live',
  value_realized: 'Value realized',
  closed: 'Closed',
}

const AREA_LABELS: Record<string, string> = {
  idea_screening: 'Idea screening',
  business_case_approval: 'Business case approval',
  delivery: 'Delivery',
  value_verification: 'Value verification',
  portfolio_oversight: 'Portfolio oversight',
}

function DecisionButtons({
  subjectType, subjectId, actor, onDone,
}: {
  subjectType: 'idea' | 'case'
  subjectId: string
  actor: string
  onDone: () => void
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const act = async (decision: 'approve' | 'reject' | 'feedback') => {
    setBusy(decision)
    setError(null)
    try {
      await decide({
        subject_type: subjectType, subject_id: subjectId, decision,
        actor: actor || undefined, comment: comment || undefined,
      })
      setComment('')
      onDone()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="row decide-row">
        <input placeholder="Feedback / rationale (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
        <button disabled={!!busy} onClick={() => act('approve')}>{busy === 'approve' ? '…' : 'Approve'}</button>
        <button className="danger" disabled={!!busy} onClick={() => act('reject')}>{busy === 'reject' ? '…' : 'Reject'}</button>
        <button className="secondary" disabled={!!busy || !comment} onClick={() => act('feedback')}>
          {busy === 'feedback' ? '…' : 'Send feedback'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}

function Pipeline({ cases }: { cases: BusinessCase[] }) {
  const stages: Stage[] = ['draft', 'proposed', 'approved', 'in_delivery', 'live', 'value_realized']
  return (
    <div className="pipeline-board">
      {stages.map((stage) => {
        const inStage = cases.filter((c) => c.stage === stage)
        const value = inStage.reduce(
          (sum, c) => sum + ((c.linked_opportunity?.estimated_annual_savings ?? 0)), 0,
        )
        return (
          <div key={stage} className="pipeline-col">
            <div className="pipeline-col-head">
              <strong>{STAGE_LABELS[stage]}</strong>
              <span className="muted small">{inStage.length} · {money(value)}/yr</span>
            </div>
            {inStage.map((c) => (
              <div key={c.id} className="pipeline-item">
                <div className="small"><strong>{c.title.replace('[Auto-draft] ', '')}</strong></div>
                <div className="muted small">
                  {c.linked_opportunity ? `${money(c.linked_opportunity.estimated_annual_savings)}/yr forecast` : 'no forecast'}
                  {c.tracking?.measured_annual_savings ? ` · ${money(c.tracking.measured_annual_savings)}/yr verified` : ''}
                </div>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

function GovernanceEditor({
  assignments, onSaved,
}: {
  assignments: Record<string, string[]>
  onSaved: () => void
}) {
  const [local, setLocal] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(assignments).map(([k, v]) => [k, v.join(', ')])),
  )
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  return (
    <div className="card">
      <h3>Governance</h3>
      <p className="muted small">
        Assign owners to each workflow area. Areas with owners only accept decisions from those
        people; empty areas are open until configured.
      </p>
      {Object.keys(AREA_LABELS).map((area) => (
        <div key={area} className="gov-row">
          <span className="funnel-label">{AREA_LABELS[area]}</span>
          <input
            placeholder="names, comma-separated"
            value={local[area] ?? ''}
            onChange={(e) => setLocal({ ...local, [area]: e.target.value })}
          />
        </div>
      ))}
      <div className="row">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setMsg(null)
            try {
              await putGovernance(
                Object.fromEntries(
                  Object.entries(local).map(([k, v]) => [k, v.split(',').map((s) => s.trim()).filter(Boolean)]),
                ),
              )
              setMsg('Saved.')
              onSaved()
            } catch (e) {
              setMsg(e instanceof Error ? e.message : String(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Saving…' : 'Save governance'}
        </button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function ScoringEditor({ onSaved }: { onSaved: () => void }) {
  const [config, setConfig] = useState<ScoringConfig | null>(null)
  const [themes, setThemes] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    getScoringConfig().then((c) => {
      setConfig(c)
      setThemes(c.priority_themes.join(', '))
    })
  }, [])

  if (!config) return null
  const ideaTotal = Object.values(config.idea_weights).reduce((a, b) => a + b, 0) || 1

  return (
    <div className="card">
      <h3>Scoring framework</h3>
      <p className="muted small">
        Leaders tune how ideas are scored and set intake guardrails — changes apply to every new
        triage immediately.
      </p>
      {Object.entries(config.idea_weights).map(([key, value]) => (
        <div key={key} className="weight-row">
          <span className="weight-label">{key.replace('_', ' ')}</span>
          <input
            type="range" min={0} max={100} value={Math.round(value * 100)}
            onChange={(e) =>
              setConfig({
                ...config,
                idea_weights: { ...config.idea_weights, [key]: Number(e.target.value) / 100 },
              })
            }
          />
          <span className="weight-pct">{Math.round((value / ideaTotal) * 100)}%</span>
        </div>
      ))}
      <input
        placeholder="Strategic priority themes, comma-separated"
        value={themes}
        onChange={(e) => setThemes(e.target.value)}
      />
      <div className="row guardrail-row">
        <label className="small">
          Min annual benefit $
          <input
            type="number"
            value={config.guardrails.min_annual_benefit || ''}
            onChange={(e) =>
              setConfig({
                ...config,
                guardrails: { ...config.guardrails, min_annual_benefit: Number(e.target.value) || 0 },
              })
            }
          />
        </label>
        <label className="small">
          <input
            type="checkbox"
            checked={config.guardrails.require_category}
            onChange={(e) =>
              setConfig({ ...config, guardrails: { ...config.guardrails, require_category: e.target.checked } })
            }
          />{' '}
          require category
        </label>
        <label className="small">
          <input
            type="checkbox"
            checked={config.guardrails.require_benefit_estimate}
            onChange={(e) =>
              setConfig({
                ...config,
                guardrails: { ...config.guardrails, require_benefit_estimate: e.target.checked },
              })
            }
          />{' '}
          require benefit estimate
        </label>
      </div>
      <div className="row">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            setMsg(null)
            try {
              await putScoringConfig({
                ...config,
                priority_themes: themes.split(',').map((s) => s.trim()).filter(Boolean),
              })
              setMsg('Saved — applies to all new triage.')
              onSaved()
            } catch (e) {
              setMsg(e instanceof Error ? e.message : String(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Saving…' : 'Save framework'}
        </button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

export default function CommandCenter({ onChanged }: Props) {
  const [queue, setQueue] = useState<CommandQueue | null>(null)
  const [actor, setActor] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)

  const refresh = async () => {
    setQueue(await getCommandQueue())
    onChanged()
  }
  useEffect(() => {
    getCommandQueue().then(setQueue)
  }, [])

  if (!queue) return <section><p className="muted">Loading…</p></section>

  const allCases = [...queue.cases_pending_approval, ...queue.cases_in_motion]

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Command center</h2>
          <p className="muted">
            Centralized approvals across the innovation lifecycle — approve, reject, or send
            feedback; the hub handles the paperwork and stage transitions.
          </p>
        </div>
        <div className="row">
          <input placeholder="Acting as… (your name)" value={actor} onChange={(e) => setActor(e.target.value)} style={{ maxWidth: 200 }} />
          <button
            className="secondary"
            disabled={autoBusy}
            onClick={async () => {
              setAutoBusy(true)
              try {
                await runAutomation()
                await refresh()
              } finally {
                setAutoBusy(false)
              }
            }}
          >
            {autoBusy ? 'Running…' : 'Run automation now'}
          </button>
        </div>
      </div>

      <h3>Ideas awaiting screening ({queue.ideas_pending.length})</h3>
      {queue.ideas_pending.length === 0 && <p className="muted small">Queue clear.</p>}
      {queue.ideas_pending.map((idea: Idea) => (
        <div key={idea.id} className="card">
          <div className="card-header">
            <div>
              <h3>{idea.title}</h3>
              <p className="muted small">
                {idea.assessment?.rationale} · score {idea.assessment?.score}
                {idea.submitter ? ` · from ${idea.submitter}` : ''}
              </p>
            </div>
            {idea.assessment && <span className="score-chip">{idea.assessment.score}</span>}
          </div>
          <DecisionButtons subjectType="idea" subjectId={idea.id} actor={actor} onDone={refresh} />
        </div>
      ))}

      <h3 className="spaced">Cases awaiting approval ({queue.cases_pending_approval.length})</h3>
      {queue.cases_pending_approval.length === 0 && <p className="muted small">Queue clear.</p>}
      {queue.cases_pending_approval.map((c) => (
        <div key={c.id} className="card">
          <div className="card-header">
            <div>
              <h3>{c.title}</h3>
              <p className="muted small">
                stage: {STAGE_LABELS[c.stage]} · {c.generated_by === 'automation' ? 'auto-drafted by the hub · ' : ''}
                {c.linked_opportunity ? `${money(c.linked_opportunity.estimated_annual_savings)}/yr forecast` : 'no linked opportunity'}
                {c.estimated_cost != null ? ` · ${money(c.estimated_cost)} est. cost` : ''}
              </p>
            </div>
            <span className="badge">{STAGE_LABELS[c.stage]}</span>
          </div>
          <DecisionButtons subjectType="case" subjectId={c.id} actor={actor} onDone={refresh} />
        </div>
      ))}

      <h3 className="spaced">Innovation pipeline</h3>
      <Pipeline cases={allCases} />

      <div className="dash-grid spaced">
        <ScoringEditor onSaved={refresh} />
        <GovernanceEditor assignments={queue.governance} onSaved={refresh} />
      </div>

      <h3 className="spaced">Decision history</h3>
      {queue.history.length === 0 ? (
        <p className="muted small">No decisions recorded yet.</p>
      ) : (
        <table className="kpi-table">
          <thead>
            <tr><th>When</th><th>Subject</th><th>Decision</th><th>By</th><th>Comment</th></tr>
          </thead>
          <tbody>
            {queue.history.map((h, i) => (
              <tr key={i}>
                <td className="muted small">{h.created_at.slice(0, 16).replace('T', ' ')}</td>
                <td>{h.subject_type} {h.subject_id}</td>
                <td><span className={`pill act-${h.action === 'approve' ? 'approve' : h.action === 'reject' ? 'intervene' : 'verify'}`}>{h.action}</span></td>
                <td>{h.actor ?? '—'}</td>
                <td className="muted small">{h.comment ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
