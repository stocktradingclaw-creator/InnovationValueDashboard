import { useEffect, useState } from 'react'
import { money } from '../api'
import type { Idea, Stage, WorkflowStep } from '../types'

interface SubmissionIdea extends Idea {
  history: { created_at: string; action: string; actor: string | null; comment: string | null }[]
  case_stage: Stage | null
  case_stage_history: { stage: Stage; entered_at: string }[]
  case_history: { created_at: string; action: string; actor: string | null; comment: string | null }[]
  needs_attention: boolean
  attention_reason: string | null
}

interface Payload {
  scope?: 'all' | 'mine'
  ideas: SubmissionIdea[]
  updates_needed: string[]
  workflow: WorkflowStep[]
}

function ReviseBox({ idea, onDone }: { idea: SubmissionIdea; onDone: () => void }) {
  const [text, setText] = useState(idea.description ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="revise-box">
      <textarea rows={3} value={text} onChange={(e) => setText(e.target.value)}
                placeholder="Answer the reviewers' feedback by revising your idea…" />
      <div className="row">
        <button disabled={busy || !text.trim()} onClick={async () => {
          setBusy(true); setError(null)
          try {
            const res = await fetch(`/api/ideas/${idea.id}/revise`, {
              method: 'PUT', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ description: text }),
            })
            if (!res.ok) throw new Error((await res.json()).detail ?? 'revision failed')
            onDone()
          } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
          finally { setBusy(false) }
        }}>{busy ? 'Sending…' : 'Send revision — back to review'}</button>
        {error && <span className="error small">{error}</span>}
      </div>
    </div>
  )
}

const FORUM_LABELS: Record<string, string> = {
  idea_screening: 'the idea screening forum',
  business_case_approval: 'executive reviewers',
  delivery: 'the delivery team',
  value_verification: 'value verification',
  portfolio_oversight: 'portfolio oversight',
}

const CASE_ROWS: [Stage, string, string][] = [
  ['proposed', 'Executive review', 'Executives weigh value, cost, and the red-team memo'],
  ['approved', 'Funding gate', 'A tranche must be released to mobilize'],
  ['in_delivery', 'Delivery', 'Being built and implemented'],
  ['live', 'Live', 'Go-live starts the measurement clock'],
  ['value_realized', 'Value verified', 'Measured against the frozen baseline'],
  ['scale', 'Scale', 'Replicated as a proven pattern'],
]

function ApprovalChain({ idea, workflow }: { idea: SubmissionIdea; workflow: WorkflowStep[] }) {
  const keys = (workflow ?? []).map((w) => w.key)
  const pos = keys.indexOf(idea.status)
  const promoted = idea.status === 'business_case'
  const stageOrder: Stage[] = CASE_ROWS.map(([st]) => st)
  const caseIdx = idea.case_stage ? stageOrder.indexOf(idea.case_stage) : -1
  const reached = (st: Stage) =>
    (idea.case_stage_history ?? []).some((h) => h.stage === st) || idea.case_stage === st

  type Row = { label: string; detail: string; state: 'done' | 'current' | 'pending' | 'ended' }
  const rows: Row[] = (workflow ?? []).map((w, i) => ({
    label: w.label,
    detail: w.gate,
    state: promoted || (pos >= 0 && i < pos) ? 'done'
      : pos === i && !promoted ? 'current' : 'pending',
  }))
  for (const [st, label, detail] of CASE_ROWS) {
    const i = stageOrder.indexOf(st)
    rows.push({
      label, detail,
      state: !promoted ? 'pending'
        : idea.case_stage === st ? 'current'
          : reached(st) || (caseIdx > i && caseIdx >= 0) ? 'done' : 'pending',
    })
  }
  if (idea.status === 'declined' || idea.status === 'backlog') {
    rows.forEach((r) => { if (r.state === 'current') r.state = 'pending' })
    rows.push({ label: idea.status === 'declined' ? 'Declined' : 'On the backlog',
                detail: idea.status === 'declined' ? 'This idea will not proceed'
                  : 'Parked — a reviewer can resume it', state: 'ended' })
  }

  const current = rows.find((r) => r.state === 'current')
  const step = pos >= 0 ? workflow[pos] : null
  const pending =
    idea.status === 'declined' ? 'No action pending — this idea was declined.'
      : idea.status === 'backlog' ? 'Waiting for a reviewer to resume it from the backlog.'
        : idea.needs_attention ? 'Waiting on YOU — answer the feedback below and send a revision.'
          : step ? `Waiting on ${FORUM_LABELS[step.forum] ?? step.forum} to decide: ${step.gate}.`
            : idea.case_stage === 'proposed' ? 'Waiting on executives to review the business case.'
              : idea.case_stage === 'approved' ? 'Approved — waiting on a funding tranche release.'
                : idea.case_stage === 'in_delivery' ? 'In delivery — waiting on go-live.'
                  : idea.case_stage === 'live' ? 'Live — waiting on the next measurement against the baseline.'
                    : current ? `Waiting at: ${current.label}.` : 'Journey complete.'

  const done = rows.filter((r) => r.state === 'done').length
  return (
    <div className="approval-chain">
      <div className="progress-wrap">
        <span className="muted small">Progress</span>
        <div className="progress"><div className="progress-bar"
          style={{ width: `${Math.round((done / rows.length) * 100)}%` }} /></div>
        <span className="small">{done}/{rows.length} stages</span>
      </div>
      <p className="small pending-action"><strong>Pending action:</strong> {pending}</p>
      {rows.map((r, i) => (
        <div key={i} className={`chain-step chain-${r.state}`}>
          <span className="chain-marker" aria-hidden="true">
            {r.state === 'done' ? '✓' : r.state === 'current' ? '●' : r.state === 'ended' ? '✕' : '○'}
          </span>
          <span><strong>{r.label}</strong> <span className="muted small">{r.detail}</span></span>
        </div>
      ))}
    </div>
  )
}

function Chain({ idea, workflow }: { idea: SubmissionIdea; workflow: WorkflowStep[] }) {
  const ideaKeys = (workflow ?? []).map((w) => w.key)
  const caseStages: Stage[] = ['proposed', 'experiment', 'approved', 'in_delivery', 'live', 'value_realized', 'scale']
  const passedIdea = (key: string) => {
    const pos = ideaKeys.indexOf(key)
    const cur = ideaKeys.indexOf(idea.status)
    if (idea.status === 'business_case') return true
    if (idea.status === 'declined' || idea.status === 'backlog') return cur === -1 ? false : pos <= cur
    return cur >= 0 && pos < cur ? true : pos === cur ? 'current' : false
  }
  const reachedCase = (stage: Stage) =>
    idea.case_stage === stage ? 'current'
      : (idea.case_stage_history ?? []).some((h) => h.stage === stage)
  return (
    <div className="chain">
      {(workflow ?? []).map((w) => {
        const state = passedIdea(w.key)
        return (
          <span key={w.key}
                className={`chain-node ${state === 'current' ? 'chain-current' : state ? 'chain-done' : ''}`}
                title={w.gate}>
            {state === true ? '✓ ' : ''}{w.label}
          </span>
        )
      })}
      <span className={`chain-node ${idea.status === 'business_case' && !idea.case_stage ? 'chain-current' : idea.status === 'business_case' ? 'chain-done' : ''}`}>
        Business case
      </span>
      {idea.case_stage && caseStages.filter((cs) => reachedCase(cs)).map((cs) => (
        <span key={cs} className={`chain-node ${reachedCase(cs) === 'current' ? 'chain-current' : 'chain-done'}`}>
          {reachedCase(cs) === 'current' ? '' : '✓ '}{cs.replace('_', ' ')}
        </span>
      ))}
      {(idea.status === 'declined' || idea.status === 'backlog') && (
        <span className="chain-node chain-ended">{idea.status}</span>
      )}
    </div>
  )
}

export default function MySubmissions({ me }: { me: { name: string; role: string } | null }) {
  const [name, setName] = useState(me?.name ?? localStorage.getItem('ivd_user') ?? '')
  const [data, setData] = useState<Payload | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = async (who: string) => {
    if (!who.trim()) return
    setBusy(true)
    try {
      const res = await fetch(`/api/my-submissions?submitter=${encodeURIComponent(who)}`)
      setData(await res.json())
      localStorage.setItem('ivd_user', who)
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => {
    if (me) { setName(me.name); load(me.name) } else if (name) load(name)
  }, [me])

  const attention = (data?.ideas ?? []).filter((i) => i.needs_attention)
  const rest = (data?.ideas ?? []).filter((i) => !i.needs_attention)

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>{data?.scope === 'all' ? 'All submissions' : 'My submissions'}</h2>
          <p className="muted">
            {data?.scope === 'all'
              ? 'Admin view — every idea submitted across the hub, with each approval chain.'
              : "Everything you've submitted, where each idea sits in the approval chain, and what needs your attention."}
          </p>
        </div>
        {me ? (
          <span className="badge">
            signed in as <strong>{me.name}</strong>{me.role === 'admin' ? ' · admin — all submissions' : ''}
          </span>
        ) : (
          <div className="row">
            <input placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && load(name)} style={{ maxWidth: 200 }} />
            <button disabled={busy || !name.trim()} onClick={() => load(name)}>
              {busy ? 'Loading…' : 'Show mine'}
            </button>
          </div>
        )}
      </div>

      {data && data.ideas.length === 0 && (
        <p className="muted">No submissions yet under "{name}" — share your first idea on the
        Idea Submission tab.</p>
      )}

      {attention.length > 0 && (
        <>
          <h3>Needs your attention ({attention.length})</h3>
          {attention.map((i) => (
            <div key={i.id} className="card attention-card">
              <div className="card-header">
                <h3>{i.title}</h3>
                <span className="pill act-verify">action needed</span>
              </div>
              <p className="small">{i.attention_reason}</p>
              <ReviseBox idea={i} onDone={() => load(name)} />
              <Chain idea={i} workflow={data!.workflow} />
            </div>
          ))}
        </>
      )}

      {rest.length > 0 && <h3 className="spaced">All submissions ({data!.ideas.length})</h3>}
      {rest.map((i) => (
        <div key={i.id} className="card">
          <div className="card-header clickable" role="button" tabIndex={0}
               onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(expanded === i.id ? null : i.id) } }}
               onClick={() => setExpanded(expanded === i.id ? null : i.id)}>
            <div>
              <h3>{i.title}</h3>
              <p className="muted small">
                {data?.scope === 'all' && i.submitter ? `from ${i.submitter} · ` : ''}
                {(i.submitted_at ?? '').slice(0, 10)}
                {i.estimated_annual_benefit ? ` · ${money(i.estimated_annual_benefit)}/yr est` : ''}
                {i.assessment ? ` · score ${i.assessment.score}` : ''}
              </p>
            </div>
            <span className={i.status === 'business_case' ? 'badge badge-ok' : 'badge'}>
              {i.status.replace('_', ' ')}
            </span>
          </div>
          <Chain idea={i} workflow={data!.workflow} />
          {expanded === i.id && (
            <div className="plan">
              <h4>Approval chain</h4>
              <ApprovalChain idea={i} workflow={data!.workflow} />
              <h4>History</h4>
              {[...(i.history ?? []).map((h) => ({ ...h, scope: 'idea' })),
                ...(i.case_history ?? []).map((h) => ({ ...h, scope: 'case' }))]
                .sort((a, b) => a.created_at.localeCompare(b.created_at))
                .map((h, idx) => (
                  <div key={idx} className="comment-row small">
                    <span className="muted">{h.created_at.slice(0, 16).replace('T', ' ')}</span>{' '}
                    <span className={`pill ${h.action === 'reject' ? 'act-intervene' : h.action === 'feedback' ? 'act-verify' : 'act-approve'}`}>
                      {h.action}
                    </span>{' '}
                    {h.actor && <strong>{h.actor}</strong>}{' '}
                    <span className="muted">{h.comment ?? ''}</span>
                  </div>
                ))}
              {(i.history ?? []).length + (i.case_history ?? []).length === 0 && (
                <p className="muted small">No decisions recorded yet — the pending action above
                  shows exactly who the ball is with.</p>
              )}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
