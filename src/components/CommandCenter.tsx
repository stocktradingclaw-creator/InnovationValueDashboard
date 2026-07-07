import { useEffect, useState } from 'react'
import {
  addExperiment, addTranche, concludeExperiment, decide, getCommandQueue, getDividends, getLearnings, redTeamCase, reviewIdea,
  getLifecycle, getPatterns, money, toast, releaseTranche, replicatePattern, runAutomation,
} from '../api'
import { CfoView, PlanView } from './BusinessCases'
import type { BusinessCase, CommandQueue, Learning, Lifecycle, Pattern, QueuedIdea, Stage } from '../types'

interface Props {
  onChanged: () => void
}

const STAGE_LABELS: Record<Stage, string> = {
  draft: 'Draft',
  proposed: 'Proposed',
  experiment: 'Experiment',
  approved: 'Approved',
  in_delivery: 'In delivery',
  live: 'Live',
  value_realized: 'Value realized',
  scale: 'Scale',
  closed: 'Closed',
}


function DecisionButtons({
  subjectType, subjectId, actor, onDone, allowExperiment,
}: {
  subjectType: 'idea' | 'case'
  subjectId: string
  actor: string
  onDone: () => void
  allowExperiment?: boolean
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const act = async (decision: 'approve' | 'reject' | 'feedback' | 'experiment') => {
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
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('not found')) {
        setError('This item no longer exists on the server (the demo data was reset or '
          + 'reverted since this queue loaded) — refreshing the queue.')
        setTimeout(onDone, 1200)
      } else {
        setError(msg)
      }
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="row decide-row">
        <input placeholder="Feedback / rationale (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
        <button disabled={!!busy} onClick={() => act('approve')}>{busy === 'approve' ? '…' : 'Approve'}</button>
        {allowExperiment && (
          <button className="secondary" disabled={!!busy} onClick={() => act('experiment')}>
            {busy === 'experiment' ? '…' : 'Run experiment first'}
          </button>
        )}
        <button className="danger" disabled={!!busy} onClick={() => act('reject')}>{busy === 'reject' ? '…' : 'Reject'}</button>
        <button className="secondary" disabled={!!busy || !comment} onClick={() => act('feedback')}>
          {busy === 'feedback' ? '…' : 'Send feedback'}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}

const IDEA_STAGE_LABEL: Record<string, string> = {
  proposed: 'Proposed',
  qualified: 'Qualified',
  prioritized: 'Prioritized',
  business_case: 'Business case',
}

function LifecycleStrip({ lifecycle }: { lifecycle: Lifecycle | null }) {
  if (!lifecycle) return null
  const caseTotal = (stages: string[]) =>
    stages.reduce((sum, s) => sum + (lifecycle.case_counts[s] ?? 0), 0)
  const steps = [
    ...lifecycle.spec.slice(0, 3).map((s) => ({
      label: IDEA_STAGE_LABEL[s.stage],
      gate: s.gate,
      count: lifecycle.idea_counts[s.stage] ?? 0,
      title: `${s.step}
${s.purpose}`,
    })),
    { label: 'Business case', gate: 'Executive review', count: caseTotal(['draft', 'proposed', 'experiment']), title: 'AI-developed case under executive review' },
    { label: 'Approved & funded', gate: 'Funding gate', count: caseTotal(['approved', 'in_delivery']), title: 'Approved; tranche release required to mobilize' },
    { label: 'Live → value', gate: 'Verified evidence', count: caseTotal(['live', 'value_realized', 'scale']), title: 'Delivering and verifying value from data' },
  ]
  return (
    <div className="lifecycle-strip" role="group" aria-label="Idea-to-portfolio lifecycle">
      {steps.map((s, i) => (
        <div key={s.label} className="lifecycle-step" title={s.title}>
          <div className="lifecycle-box">
            <strong>{s.count}</strong>
            <span>{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div className="lifecycle-gate" title={s.gate}>
              <span className="muted small">{s.gate.split(' (')[0]}</span>
              <span className="lifecycle-arrow">→</span>
            </div>
          )}
        </div>
      ))}
      <span className="muted small lifecycle-exits">
        backlog {lifecycle.idea_terminal.backlog} · declined {lifecycle.idea_terminal.declined} ·
        killed/closed {lifecycle.case_counts.closed ?? 0}
      </span>
    </div>
  )
}

function GateActions({
  ideaId, actor, actions, onDone,
}: {
  ideaId: string
  actor: string
  actions: [string, string, string][]  // [decision, label, className]
  onDone: () => void
}) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  return (
    <>
      <div className="row decide-row">
        <input placeholder="Rationale / feedback (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
        {actions.map(([decision, label, cls]) => (
          <button
            key={decision}
            className={cls}
            disabled={!!busy && busy !== `confirm-${decision}`}
            onClick={async () => {
              const fire = async (): Promise<boolean> => {
                try {
                  await decide({
                    subject_type: 'idea', subject_id: ideaId,
                    decision: decision as Parameters<typeof decide>[0]['decision'],
                    actor: actor || undefined, comment: comment || undefined,
                  })
                  setComment('')
                  onDone()
                  return true
                } catch (e) {
                  const msg = e instanceof Error ? e.message : String(e)
                  if (msg.includes('not found')) {
                    setError('This idea no longer exists on the server (the demo data was '
                      + 'reset or reverted since this queue loaded) — refreshing the queue.')
                    setTimeout(onDone, 1200)
                  } else if (msg.includes('requires') || msg.includes('profile')) {
                    setError(`${msg} — set who you are in the "Acting as" field at the top.`)
                  } else {
                    setError(msg)
                  }
                } finally {
                  setBusy(null)
                }
                return false
              }
              setError(null)
              if (decision === 'reject') {
                // destructive: explicit two-tap confirmation with an exit
                if (busy !== 'confirm-reject') {
                  setBusy('confirm-reject')
                  window.setTimeout(() => setBusy((b) => b === 'confirm-reject' ? null : b), 8000)
                  return
                }
                setBusy(decision)
                if (await fire()) toast('Declined.')
                return
              }
              if (decision === 'hold' && !comment.trim()) {
                const why = window.prompt('Why hold this? (required — the backlog shows it)')
                if (!why) { setBusy(null); return }
                setComment(why)
              }
              if (decision === 'advance' || decision === 'develop' || decision === 'hold') {
                // commit immediately; offer a server-backed undo
                setBusy(decision)
                if (!(await fire())) return
                if (decision !== 'develop') {
                  toast(`${label} — done.`, async () => {
                    await decide({ subject_type: 'idea', subject_id: ideaId,
                                   decision: 'revert_last' as Parameters<typeof decide>[0]['decision'],
                                   actor: actor || undefined }).catch(() => {})
                    onDone()
                  })
                } else {
                  toast('Business case drafted — waiting at executive review.')
                }
                return
              }
              setBusy(decision)
              if (await fire()) toast('Feedback sent to the submitter.')
            }}
          >
            {busy === `confirm-${decision}` ? 'Decline — are you sure?'
              : busy === decision ? 'Applying…' : label}
          </button>
        ))}
      {busy === 'confirm-reject' && (
        <button type="button" className="chip" onClick={() => setBusy(null)}>
          Cancel — keep it</button>
      )}
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}

function RubricPanel({ ideaId, actor, criteria, onDone }: {
  ideaId: string; actor: string; criteria: string[]; onDone: () => void
}) {
  const [open, setOpen] = useState(false)
  const [scores, setScores] = useState<Record<string, number>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const crits = criteria.length > 0 ? criteria : ['Impact', 'Feasibility', 'Strategic fit']
  if (!open) {
    return <button type="button" className="chip" onClick={() => setOpen(true)}>Score against criteria</button>
  }
  return (
    <div className="rubric">
      {crits.map((c) => (
        <label key={c} className="rubric-row">
          <span className="small">{c}</span>
          <input type="range" min={1} max={5} step={1} value={scores[c] ?? 3}
                 aria-label={`Score for ${c}`}
                 onChange={(e) => setScores({ ...scores, [c]: Number(e.target.value) })} />
          <strong>{scores[c] ?? 3}</strong>
        </label>
      ))}
      <div className="row">
        <button disabled={busy}
                onClick={async () => {
                  if (!actor.trim()) {
                    setMsg('Tell the hub who you are first — sign in or fill "Acting as" at the top.')
                    return
                  }
                  setBusy(true); setMsg(null)
                  try {
                    const filled = Object.fromEntries(crits.map((c) => [c, scores[c] ?? 3]))
                    await reviewIdea(ideaId, { reviewer: actor, scores: filled })
                    setMsg('Review saved.'); setOpen(false); onDone()
                  } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
                  finally { setBusy(false) }
                }}>{busy ? 'Saving…' : 'Save review'}</button>
        <button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function IdeaGateCard({
  idea, actor, actions, criteria, onDone,
}: {
  idea: QueuedIdea
  actor: string
  actions: [string, string, string][]
  criteria: string[]
  onDone: () => void
}) {
  return (
    <div className="card" draggable
         onDragStart={(e) => e.dataTransfer.setData('text/idea-id', idea.id)}>
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
      <div className="row gate-checklist">
        {idea.gate_checklist.map((c) => (
          <span key={c.check} className={c.passed ? 'pill act-approve' : 'pill act-verify'}>
            {c.passed ? '✓' : '?'} {c.check}
          </span>
        ))}
      </div>
      <div className="row">
        {idea.assessment?.recommendation === 'fast_track' && (
          <button className="chip" title="Triage recommends fast-tracking: runs every gate and drafts the business case in one step"
                  onClick={async () => {
                    try {
                      await decide({ subject_type: 'idea', subject_id: idea.id,
                                     decision: 'fast_track' as Parameters<typeof decide>[0]['decision'],
                                     actor: actor || undefined })
                      toast('Fast-tracked — business case drafted, waiting at executive review.')
                      onDone()
                    } catch (e) {
                      toast(`Fast-track failed: ${e instanceof Error ? e.message : e}`)
                    }
                  }}>⚡ Fast-track to business case</button>
        )}
        {idea.review_summary && idea.review_summary.count > 0 && (
          <span className="pill act-approve">
            {idea.review_summary.count} review(s) · avg {idea.review_summary.average}/5
          </span>
        )}
        <RubricPanel ideaId={idea.id} actor={actor} criteria={criteria} onDone={onDone} />
      </div>
      <GateActions ideaId={idea.id} actor={actor} actions={actions} onDone={onDone} />
    </div>
  )
}

function PortfolioRegister({ lifecycle }: { lifecycle: Lifecycle | null }) {
  if (!lifecycle || lifecycle.register.length === 0) return null
  const entries = lifecycle.register
  const maxImpact = Math.max(...entries.map((e) => e.impact), 1)
  return (
    <div className="card matrix-card">
      <h3>Portfolio register <span className="muted small">impact vs readiness</span></h3>
      <div className="matrix">
        <span className="matrix-corner tl">Prioritize</span>
        <span className="matrix-corner tr">Fast-track</span>
        <span className="matrix-corner bl">Hold / develop info</span>
        <span className="matrix-corner br">Quick validation</span>
        {entries.map((e) => (
          <span
            key={e.id}
            className={`dot ${e.status === 'prioritized' ? 'dot-quick_win' : 'dot-strategic_bet'}`}
            style={{
              left: `${5 + e.readiness * 90}%`,
              top: `${95 - Math.min(Math.log1p(e.impact) / Math.log1p(maxImpact), 1) * 90}%`,
            }}
            title={`${e.title}
$${e.impact.toLocaleString()}/yr est · readiness ${Math.round(e.readiness * 100)}% · ${e.status}`}
          />
        ))}
      </div>
      <div className="matrix-axes muted small">
        <span>← lower readiness</span>
        <span>higher readiness →</span>
      </div>
    </div>
  )
}

function TrancheManager({ bc, actor, onDone }: { bc: BusinessCase; actor: string; onDone: () => void }) {
  const [label, setLabel] = useState('')
  const [amount, setAmount] = useState('')
  const [milestone, setMilestone] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="tranche-box">
      {bc.funding.tranches.map((t) => (
        <div key={t.id} className="row small tranche-row">
          <span>{t.label} — {money(t.amount)} <span className="muted">on "{t.milestone}"</span></span>
          {t.status === 'released' ? (
            <span className="badge badge-ok">released {t.released_at?.slice(0, 10)}</span>
          ) : (
            <button
              className="secondary"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                setError(null)
                try {
                  await releaseTranche(bc.id, t.id, actor || undefined)
                  onDone()
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e))
                } finally {
                  setBusy(false)
                }
              }}
            >
              Release
            </button>
          )}
        </div>
      ))}
      <div className="row">
        <input placeholder="Tranche label" value={label} onChange={(e) => setLabel(e.target.value)} />
        <input type="number" placeholder="Amount $" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <input placeholder="Released when… (milestone)" value={milestone} onChange={(e) => setMilestone(e.target.value)} />
        <button
          className="secondary"
          disabled={busy || !label || !amount || !milestone}
          onClick={async () => {
            setBusy(true)
            try {
              await addTranche(bc.id, { label, amount: Number(amount), milestone })
              setLabel(''); setAmount(''); setMilestone('')
              onDone()
            } finally {
              setBusy(false)
            }
          }}
        >
          Plan tranche
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function ExperimentPanel({ bc, onDone }: { bc: BusinessCase; onDone: () => void }) {
  const [hypothesis, setHypothesis] = useState('')
  const [method, setMethod] = useState('')
  const [criteria, setCriteria] = useState('')
  const [learnings, setLearnings] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const open = bc.experiments.filter((e) => !e.concluded_at)
  return (
    <div className="card">
      <div className="card-header">
        <h3>{bc.title.replace('[Auto-draft] ', '')}</h3>
        <span className="badge">experiment</span>
      </div>
      {bc.experiments.map((e) => (
        <div key={e.id} className="pipeline-item">
          <div className="small"><strong>H:</strong> {e.hypothesis}</div>
          <div className="muted small">Method: {e.method} · Success: {e.success_criteria}</div>
          {e.concluded_at ? (
            <div className="small">
              <span className={`pill ${e.outcome === 'proceed' ? 'act-approve' : e.outcome === 'kill' ? 'act-intervene' : 'act-verify'}`}>
                {e.outcome}
              </span>{' '}
              <span className="muted">{e.learnings}</span>
            </div>
          ) : (
            <div className="row">
              <input
                placeholder="Learnings (required to conclude)"
                value={learnings}
                onChange={(ev) => setLearnings(ev.target.value)}
              />
              {(['proceed', 'kill', 'pivot'] as const).map((outcome) => (
                <button
                  key={outcome}
                  className={outcome === 'kill' ? 'danger' : outcome === 'proceed' ? '' : 'secondary'}
                  disabled={!!busy || !learnings.trim()}
                  onClick={async () => {
                    setBusy(outcome)
                    try {
                      await concludeExperiment(bc.id, e.id, { outcome, learnings })
                      setLearnings('')
                      onDone()
                    } finally {
                      setBusy(null)
                    }
                  }}
                >
                  {busy === outcome ? '…' : outcome}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      {open.length === 0 && (
        <div className="row">
          <input placeholder="Hypothesis" value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} />
          <input placeholder="Method (cheap + fast)" value={method} onChange={(e) => setMethod(e.target.value)} />
          <input placeholder="Success criteria" value={criteria} onChange={(e) => setCriteria(e.target.value)} />
          <button
            disabled={!!busy || !hypothesis || !method || !criteria}
            onClick={async () => {
              setBusy('add')
              try {
                await addExperiment(bc.id, { hypothesis, method, success_criteria: criteria })
                setHypothesis(''); setMethod(''); setCriteria('')
                onDone()
              } finally {
                setBusy(null)
              }
            }}
          >
            {busy === 'add' ? '…' : 'Start experiment'}
          </button>
        </div>
      )}
    </div>
  )
}

function RedTeam({ bc, onDone }: { bc: BusinessCase; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const memo = bc.red_team
  return (
    <div className="redteam">
      {!memo && (
        <button className="chip" disabled={busy} onClick={async () => {
          setBusy(true)
          try { await redTeamCase(bc.id); onDone() } finally { setBusy(false) }
        }}>{busy ? 'Prosecuting…' : '⚔ Red-team this case'}</button>
      )}
      {memo && (
        <div className="redteam-memo">
          <p className="small"><strong>⚔ Red team ({memo.generated_by}):</strong>{' '}
            killer assumption — {memo.killer_assumption}</p>
          <ul className="muted small">
            {memo.failure_modes.slice(0, 3).map((f) => <li key={f}>{f}</li>)}
          </ul>
          <p className="muted small"><strong>Demand before funding:</strong> {memo.recommendation}</p>
        </div>
      )}
    </div>
  )
}

function LearningLibrary() {
  const [lessons, setLessons] = useState<Learning[]>([])
  const [dividends, setDividends] = useState<Record<string, number>>({})
  useEffect(() => {
    getDividends().then((r) => setDividends(
      Object.fromEntries(r.dividends.map((d) => [d.case_id, d.citations])))).catch(() => {})
  }, [])
  useEffect(() => {
    getLearnings().then((r) => setLessons(r.learnings)).catch(() => {})
  }, [])
  if (lessons.length === 0) return null
  return (
    <>
      <h3 className="spaced">Learning library <span className="muted small">kills are tuition, not failure</span></h3>
      <div className="card">
        {lessons.map((l, i) => (
          <div key={i} className="comment-row small">
            <span className={`pill ${l.outcome === 'proceed' ? 'act-approve' : l.outcome === 'kill' ? 'act-intervene' : 'act-verify'}`}>
              {l.outcome}
            </span>{' '}
            <strong>{l.case_title}</strong> <span className="muted">— {l.learnings}</span>
            {dividends[l.case_id] > 0 && (
              <span className="pill act-approve" title="times this learning informed a new idea">
                ↻ {dividends[l.case_id]} dividend{dividends[l.case_id] > 1 ? 's' : ''}
              </span>
            )}
          </div>
        ))}
      </div>
    </>
  )
}

function PatternLibrary({ onDone }: { onDone: () => void }) {
  const [patterns, setPatterns] = useState<Pattern[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  useEffect(() => {
    getPatterns().then((r) => setPatterns(r.patterns)).catch(() => {})
  }, [])
  if (patterns.length === 0) return null
  return (
    <>
      <h3 className="spaced">Pattern library — proven wins, ready to replicate</h3>
      {patterns.map((p) => (
        <div key={p.case_id} className="card">
          <div className="card-header">
            <div>
              <h3>{p.title}</h3>
              <p className="muted small">
                {p.category} · verified {p.measured_annual_savings ? money(p.measured_annual_savings) : '—'}/yr at origin
                {p.story.credited_to ? ` · started by ${p.story.credited_to}` : ''}
              </p>
            </div>
            <button
              disabled={busy === p.case_id}
              onClick={async () => {
                setBusy(p.case_id)
                try {
                  await replicatePattern(p.case_id)
                  onDone()
                } finally {
                  setBusy(null)
                }
              }}
            >
              {busy === p.case_id ? 'Replicating…' : 'Replicate elsewhere'}
            </button>
          </div>
          <div className="story small">
            <p><strong>The problem:</strong> {p.story.problem}</p>
            {p.story.what_we_tried.length > 0 && (
              <p>
                <strong>What we tried:</strong>{' '}
                {p.story.what_we_tried.map((e) => `${e.hypothesis} → ${e.outcome}: ${e.learnings}`).join(' · ')}
              </p>
            )}
            {p.story.human_evidence.length > 0 && (
              <p>
                <strong>Human evidence:</strong>{' '}
                {p.story.human_evidence.map((h) => `${h.kpi}: ${h.value}`).join(' · ')}
              </p>
            )}
          </div>
        </div>
      ))}
    </>
  )
}

function Pipeline({ cases }: { cases: BusinessCase[] }) {
  const stages: Stage[] = ['draft', 'proposed', 'experiment', 'approved', 'in_delivery', 'live', 'value_realized', 'scale']
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

export default function CommandCenter({ onChanged }: Props) {
  const [queue, setQueue] = useState<CommandQueue | null>(null)
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null)
  const [actor, setActor] = useState(localStorage.getItem('ivd_user') ?? '')
  const [openGates, setOpenGates] = useState<Record<string, boolean>>({})
  const [openCase, setOpenCase] = useState<string | null>(null)
  const [autoBusy, setAutoBusy] = useState(false)

  const refresh = async () => {
    // sync the rest of the app first so any lazy automation sweep lands
    // before we read the queue — the board must reflect the final state
    await Promise.resolve(onChanged())
    setQueue(await getCommandQueue())
    setLifecycle(await getLifecycle().catch(() => null))
  }
  useEffect(() => {
    getCommandQueue().then(setQueue)
    getLifecycle().then(setLifecycle).catch(() => {})
  }, [])

  if (!queue) {
    return (
      <section aria-busy="true" aria-label="Loading command center">
        <div className="skeleton sk-line" style={{ width: '40%' }} />
        {[0, 1, 2].map((i) => <div key={i} className="card skeleton sk-block" style={{ height: 90 }} />)}
      </section>
    )
  }

  const allCases = [
    ...queue.cases_pending_approval, ...queue.cases_in_experiment, ...queue.cases_in_motion,
  ]
  const firstBusy = queue.idea_steps.findIndex((st) => st.ideas.length > 0)
  const isOpen = (key: string, i: number) =>
    openGates[key] ?? (i === (firstBusy === -1 ? 0 : firstBusy))

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
          {localStorage.getItem('ivd_user') ? (
            <span className="badge" title="Change who you are from the profile menu, top right">
              Deciding as <strong>{actor}</strong>
            </span>
          ) : (
            <input placeholder="Acting as… (your name)" value={actor} onChange={(e) => setActor(e.target.value)} style={{ maxWidth: 200 }} />
          )}
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

      <nav className="cc-nav" aria-label="Command center sections">
        {[
          ...queue.idea_steps.map((st) => [`cc-step-${st.key}`, `${st.label} ${st.ideas.length}`]),
          ['cc-cases', `Approvals ${queue.cases_pending_approval.length}`],
          ['cc-experiments', `Experiments ${queue.cases_in_experiment.length}`],
          ['cc-pipeline', 'Pipeline'],
          ['cc-history', 'History'],
        ].map(([id, label]) => (
          <button key={id} className="chip"
                  onClick={() => document.getElementById(id as string)?.scrollIntoView({ behavior: 'smooth' })}>
            {label}
          </button>
        ))}
      </nav>

      <LifecycleStrip lifecycle={lifecycle} />

      {queue.cost_of_delay && queue.cost_of_delay.total_burned > 0 && (
        <p className="muted small delay-line">
          ⏱ Deciding faster is worth money: an estimated{' '}
          <strong>{money(queue.cost_of_delay.total_burned)}</strong> has gone unrealized while{' '}
          {queue.cost_of_delay.items.length} item(s) waited — longest:{' '}
          {queue.cost_of_delay.items[0].title} ({queue.cost_of_delay.items[0].days_waiting}d).
        </p>
      )}

      {queue.automation_ran && (queue.automation_ran.drafted > 0 || queue.automation_ran.advanced > 0
        || queue.automation_ran.observed > 0) && (
        <p className="muted small">
          ⚙ Hub automation ran with this refresh: {queue.automation_ran.drafted} case(s) drafted
          from detected opportunities, {queue.automation_ran.advanced} advanced,{' '}
          {queue.automation_ran.observed} metric(s) observed — those changes appear on this
          board too, not because of your last decision.
        </p>
      )}

      {queue.idea_steps.map((step, i) => (
        <div key={step.key}
             onDragOver={(e) => { if (i > 0) e.preventDefault() }}
             onDrop={async (e) => {
               const id = e.dataTransfer.getData('text/idea-id')
               if (!id || i === 0) return
               const from = queue.idea_steps.findIndex((st) => st.ideas.some((x) => x.id === id))
               if (from !== i - 1) return  // only the next gate accepts a drop
               try {
                 await decide({ subject_type: 'idea', subject_id: id, decision: 'advance',
                                actor: actor || undefined,
                                comment: 'advanced by drag on the board' })
                 toast('Gate passed.')
               } catch (e) {
                 toast(`Could not pass the gate: ${e instanceof Error ? e.message : e}`)
               }
               refresh()
             }}>
          <h3 className={`gate-head ${i > 0 ? 'spaced' : ''}`} id={`cc-step-${step.key}`}
              role="button" tabIndex={0} aria-expanded={isOpen(step.key, i)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpenGates({ ...openGates, [step.key]: !isOpen(step.key, i) }) } }}
              onClick={() => setOpenGates({ ...openGates, [step.key]: !isOpen(step.key, i) })}>
            <span className={`chev ${isOpen(step.key, i) ? 'chev-open' : ''}`} aria-hidden="true">▸</span>{' '}
            Gate {i + 1} — {step.gate} ({step.ideas.length})
            {i > 0 && <span className="muted small"> · drop a card here to pass its gate</span>}
          </h3>
          {isOpen(step.key, i) && (<>
          <p className="muted small">{step.purpose}</p>
          {i === queue.idea_steps.length - 1 && <PortfolioRegister lifecycle={lifecycle} />}
          {step.ideas.length === 0 && (
            <p className="muted small">All caught up at this gate.</p>
          )}
          {step.ideas.map((idea) => (
            <IdeaGateCard
              key={idea.id} idea={idea} actor={actor} criteria={step.criteria ?? []} onDone={refresh}
              actions={step.is_last
                ? [['develop', 'Develop AI business case', ''], ['hold', 'Hold (backlog)', 'secondary']]
                : i === 0
                  ? [['advance', 'Pass gate', ''], ['reject', 'Decline', 'danger'], ['feedback', 'Send feedback', 'secondary']]
                  : [['advance', 'Pass gate', ''], ['hold', 'Hold (backlog)', 'secondary'], ['reject', 'Decline', 'danger']]}
            />
          ))}
          </>)}
        </div>
      ))}
      {queue.idea_backlog.length > 0 && (
        <>
          <h3 className="spaced">Backlog ({queue.idea_backlog.length}) — parked, not forgotten</h3>
          {queue.idea_backlog.map((i) => (
            <div key={i.id} className="card">
              <div className="card-header">
                <div>
                  <h3>{i.title}</h3>
                  <p className="muted small">
                    {(i as unknown as { held_reason?: string }).held_reason
                      ? `held: ${(i as unknown as { held_reason?: string }).held_reason}`
                      : 'no hold reason recorded'}
                  </p>
                </div>
                <button onClick={async () => {
                  try {
                    await decide({ subject_type: 'idea', subject_id: i.id, decision: 'resume',
                                   actor: actor || undefined })
                    toast('Back in review.')
                  } catch (e) {
                    toast(`Could not resume: ${e instanceof Error ? e.message : e}`)
                  }
                  refresh()
                }}>Resume review</button>
              </div>
            </div>
          ))}
        </>
      )}

      <h3 className="spaced" id="cc-cases">Gate 4 — Executive review ({queue.cases_pending_approval.length})</h3>
      {queue.cases_pending_approval.length === 0 && (
        <p className="muted small">No cases awaiting executive review.</p>
      )}
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
          <button className="chip" aria-expanded={openCase === c.id}
                  onClick={() => setOpenCase(openCase === c.id ? null : c.id)}>
            {openCase === c.id ? 'Hide business case' : '▤ Review business case & ROI model'}
          </button>
          {openCase === c.id && (<>
            <CfoView caseId={c.id} title={c.title} description={c.description} />
            <PlanView plan={c.roi_plan} />
          </>)}
          <RedTeam bc={c} onDone={refresh} />
          {c.funding.planned > 0 && (
            <p className="muted small">
              Funding: {money(c.funding.released)} released of {money(c.funding.planned)} planned
            </p>
          )}
          <DecisionButtons
            subjectType="case" subjectId={c.id} actor={actor} onDone={refresh}
            allowExperiment={c.stage === 'draft' || c.stage === 'proposed'}
          />
          <TrancheManager bc={c} actor={actor} onDone={refresh} />
        </div>
      ))}

      <h3 className="spaced" id="cc-experiments">Experiments in flight ({queue.cases_in_experiment.length})</h3>
      {queue.cases_in_experiment.length === 0 && (
        <p className="muted small">
          None running. Healthy portfolios validate risky bets with cheap experiments — and kill
          40–60% of them. Use "Run experiment first" on a pending case.
        </p>
      )}
      {queue.cases_in_experiment.map((c) => (
        <ExperimentPanel key={c.id} bc={c} onDone={refresh} />
      ))}

      <h3 className="spaced" id="cc-pipeline">Innovation pipeline</h3>
      <Pipeline cases={allCases} />

      <LearningLibrary />

      <PatternLibrary onDone={refresh} />


      <h3 className="spaced" id="cc-history">Decision history</h3>
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
