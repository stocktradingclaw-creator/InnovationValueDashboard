import { useEffect, useState } from 'react'
import {
  addExperiment, addTranche, concludeExperiment, createChallenge, createInitiative, decide,
  demoGenerate, demoRevert, getDemoStatus, getLifecycle,
  getCommandQueue, getLearnings, getPatterns, getScoringConfig, money, putGovernance,
  putScoringConfig, releaseTranche, replicatePattern, runAutomation,
} from '../api'
import type { BusinessCase, CommandQueue, DemoStatus, Learning, Lifecycle, Pattern, QueuedIdea, ScoringConfig, Stage } from '../types'

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

const AREA_LABELS: Record<string, string> = {
  idea_screening: 'Idea screening',
  business_case_approval: 'Business case approval',
  delivery: 'Delivery',
  value_verification: 'Value verification',
  portfolio_oversight: 'Portfolio oversight',
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
            disabled={!!busy}
            onClick={async () => {
              setBusy(decision)
              setError(null)
              try {
                await decide({
                  subject_type: 'idea', subject_id: ideaId,
                  decision: decision as Parameters<typeof decide>[0]['decision'],
                  actor: actor || undefined, comment: comment || undefined,
                })
                setComment('')
                onDone()
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
              } finally {
                setBusy(null)
              }
            }}
          >
            {busy === decision ? '…' : label}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}

function IdeaGateCard({
  idea, actor, actions, onDone,
}: {
  idea: QueuedIdea
  actor: string
  actions: [string, string, string][]
  onDone: () => void
}) {
  return (
    <div className="card">
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

function DemoStudio({ onDone }: { onDone: () => void }) {
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [industries, setIndustries] = useState<string[]>([])
  const [clientName, setClientName] = useState('')
  const [industry, setIndustry] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    getDemoStatus().then((r) => {
      setStatus(r.demo)
      setIndustries(r.industries)
    }).catch(() => {})
  useEffect(() => { load() }, [])

  return (
    <div className="card demo-studio">
      <h3>Demo studio</h3>
      <p className="muted small">
        Tailor the portfolio for a client presentation: pick an industry, name the client, and the
        hub generates strategic initiatives with tagged, triaged ideas. Revert restores the exact
        pre-demo baseline — nothing bloats the data you present next time.
      </p>
      {status ? (
        <>
          <div className="banner-ok">
            Active demo: <strong>{status.client}</strong> ({status.industry}) —{' '}
            {status.initiatives} initiatives, {status.ideas} ideas, generated by{' '}
            {status.generated_by} on {status.generated_at.slice(0, 10)}.
          </div>
          <button
            className="danger"
            disabled={busy === 'revert'}
            onClick={async () => {
              setBusy('revert')
              setError(null)
              try {
                await demoRevert()
                await load()
                onDone()
              } catch (e) {
                setError(e instanceof Error ? e.message : String(e))
              } finally {
                setBusy(null)
              }
            }}
          >
            {busy === 'revert' ? 'Reverting…' : 'Revert to baseline'}
          </button>
        </>
      ) : (
        <>
          <div className="row">
            <input placeholder="Client name — e.g. Meridian Health" value={clientName} onChange={(e) => setClientName(e.target.value)} />
            <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
              <option value="">Pick an industry…</option>
              {industries.map((i) => <option key={i} value={i}>{i}</option>)}
            </select>
          </div>
          <input
            placeholder="Presentation focus (optional) — e.g. cost takeout in claims operations"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="row">
            <button
              disabled={busy === 'generate' || !clientName.trim() || !industry}
              onClick={async () => {
                setBusy('generate')
                setError(null)
                try {
                  await demoGenerate({ client: clientName, industry, notes: notes || undefined })
                  setClientName(''); setIndustry(''); setNotes('')
                  await load()
                  onDone()
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e))
                } finally {
                  setBusy(null)
                }
              }}
            >
              {busy === 'generate' ? 'Generating portfolio…' : 'Generate client portfolio'}
            </button>
            <span className="muted small">Snapshots the baseline first — fully reversible.</span>
          </div>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function InitiativeCreator({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState('')
  const [objective, setObjective] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="card">
      <h3>Declare a strategic initiative</h3>
      <p className="muted small">
        Initiatives group ideas and cases under a leadership objective; tagged ideas score as
        strategically aligned and value rolls up per initiative.
      </p>
      <div className="row">
        <input placeholder="Name — e.g. Cloud cost excellence" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <input placeholder="Objective — what outcome does this initiative exist to deliver?" value={objective} onChange={(e) => setObjective(e.target.value)} />
      <div className="row">
        <button
          disabled={busy || !name.trim() || !objective.trim()}
          onClick={async () => {
            setBusy(true)
            try {
              await createInitiative({ name, objective })
              setName(''); setObjective('')
              onDone()
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Creating…' : 'Create initiative'}
        </button>
      </div>
    </div>
  )
}

function ChallengeCreator({ onDone }: { onDone: () => void }) {
  const [title, setTitle] = useState('')
  const [question, setQuestion] = useState('')
  const [theme, setTheme] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <div className="card">
      <h3>Launch a challenge</h3>
      <p className="muted small">
        Targeted campaigns beat suggestion boxes — pose a strategic question and ideas submitted
        against it score as aligned automatically.
      </p>
      <div className="row">
        <input placeholder="Title — e.g. Cut cloud waste" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input placeholder="Theme (optional)" value={theme} onChange={(e) => setTheme(e.target.value)} />
      </div>
      <input
        placeholder='The "how might we…" question'
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
      />
      <div className="row">
        <button
          disabled={busy || !title.trim() || !question.trim()}
          onClick={async () => {
            setBusy(true)
            try {
              await createChallenge({ title, question, theme: theme || undefined })
              setTitle(''); setQuestion(''); setTheme('')
              onDone()
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Launching…' : 'Launch challenge'}
        </button>
      </div>
    </div>
  )
}

function LearningLibrary() {
  const [lessons, setLessons] = useState<Learning[]>([])
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
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null)
  const [actor, setActor] = useState('')
  const [autoBusy, setAutoBusy] = useState(false)

  const refresh = async () => {
    setQueue(await getCommandQueue())
    setLifecycle(await getLifecycle().catch(() => null))
    onChanged()
  }
  useEffect(() => {
    getCommandQueue().then(setQueue)
    getLifecycle().then(setLifecycle).catch(() => {})
  }, [])

  if (!queue) return <section><p className="muted">Loading…</p></section>

  const allCases = [
    ...queue.cases_pending_approval, ...queue.cases_in_experiment, ...queue.cases_in_motion,
  ]

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

      <nav className="cc-nav" aria-label="Command center sections">
        {[
          ['cc-ideas', `Screening ${queue.idea_queues.screening.length}`],
          ['cc-prioritize', `Prioritization ${queue.idea_queues.prioritization.length}`],
          ['cc-develop', `Development ${queue.idea_queues.development.length}`],
          ['cc-cases', `Approvals ${queue.cases_pending_approval.length}`],
          ['cc-experiments', `Experiments ${queue.cases_in_experiment.length}`],
          ['cc-pipeline', 'Pipeline'],
          ['cc-setup', 'Frameworks'],
          ['cc-demo', 'Demo studio'],
          ['cc-history', 'History'],
        ].map(([id, label]) => (
          <button
            key={id}
            className="chip"
            onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })}
          >
            {label}
          </button>
        ))}
      </nav>

      <LifecycleStrip lifecycle={lifecycle} />

      <h3 id="cc-ideas">Gate 1 — Qualification ({queue.idea_queues.screening.length})</h3>
      <p className="muted small">
        Is it sponsored, novel, and aligned? Qualified ideas move to portfolio prioritization.
      </p>
      {queue.idea_queues.screening.length === 0 && (
        <p className="muted small">All caught up — every new idea has been screened.</p>
      )}
      {queue.idea_queues.screening.map((idea) => (
        <IdeaGateCard
          key={idea.id} idea={idea} actor={actor} onDone={refresh}
          actions={[['qualify', 'Qualify', ''], ['reject', 'Decline', 'danger'], ['feedback', 'Send feedback', 'secondary']]}
        />
      ))}

      <h3 className="spaced" id="cc-prioritize">Gate 2 — Portfolio prioritization ({queue.idea_queues.prioritization.length})</h3>
      <p className="muted small">
        Impact vs capability and capacity — only prioritized ideas earn an AI business case.
        {queue.idea_queues.backlog.length > 0 && ` ${queue.idea_queues.backlog.length} on the backlog.`}
      </p>
      <PortfolioRegister lifecycle={lifecycle} />
      {queue.idea_queues.prioritization.length === 0 && (
        <p className="muted small">Nothing waiting to be ranked — qualified ideas will appear here.</p>
      )}
      {queue.idea_queues.prioritization.map((idea) => (
        <IdeaGateCard
          key={idea.id} idea={idea} actor={actor} onDone={refresh}
          actions={[['prioritize', 'Prioritize', ''], ['hold', 'Hold (backlog)', 'secondary'], ['reject', 'Decline', 'danger']]}
        />
      ))}

      <h3 className="spaced" id="cc-develop">Gate 3 — Business case development ({queue.idea_queues.development.length})</h3>
      <p className="muted small">
        The hub develops the case with AI — ROI plan, KPIs, and a frozen evidence baseline —
        then it lands in executive review below.
      </p>
      {queue.idea_queues.development.length === 0 && (
        <p className="muted small">No prioritized ideas awaiting a business case — the AI is ready when they are.</p>
      )}
      {queue.idea_queues.development.map((idea) => (
        <IdeaGateCard
          key={idea.id} idea={idea} actor={actor} onDone={refresh}
          actions={[['develop', 'Develop AI business case', ''], ['hold', 'Hold (backlog)', 'secondary']]}
        />
      ))}

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

      <div className="dash-grid spaced" id="cc-setup">
        <ScoringEditor onSaved={refresh} />
        <GovernanceEditor assignments={queue.governance} onSaved={refresh} />
      </div>

      <div className="dash-grid spaced">
        <ChallengeCreator onDone={refresh} />
        <InitiativeCreator onDone={refresh} />
      </div>

      <div id="cc-demo"><DemoStudio onDone={refresh} /></div>

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
