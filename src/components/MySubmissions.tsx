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
                <p className="muted small">No decisions yet — your idea is awaiting the first gate.</p>
              )}
            </div>
          )}
        </div>
      ))}
    </section>
  )
}
