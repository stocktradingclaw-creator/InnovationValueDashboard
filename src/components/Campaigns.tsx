import { useEffect, useState } from 'react'
import { closeChallenge, createChallenge, getChallenges, money, radarScan, toast } from '../api'
import type { Challenge, Idea } from '../types'

const PHASES = ['Launch', 'Collect', 'Review', 'Convert', 'Close'] as const

function phaseOf(c: Challenge, ideas: Idea[]) {
  const mine = ideas.filter((i) => i.challenge_id === c.id)
  if (c.status !== 'active') return 4
  if (mine.some((i) => i.status === 'business_case')) return 3
  if (mine.some((i) => i.status !== 'proposed')) return 2
  if (mine.length > 0) return 1
  return 0
}

export default function Campaigns({ ideas, onChanged }: { ideas: Idea[]; onChanged: () => void }) {
  const [challenges, setChallenges] = useState<Challenge[]>([])
  const [title, setTitle] = useState('')
  const [question, setQuestion] = useState('')
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [draft, setDraft] = useState<Awaited<ReturnType<typeof radarScan>> | null>(null)
  const load = () => getChallenges().then((r) => setChallenges(r.challenges)).catch(() => {})
  useEffect(() => { load() }, [])

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Innovation campaigns</h2>
          <p className="muted">
            Run a focused call for ideas across the enterprise, end to end: launch → collect →
            review at the standard gates → convert to business cases → close with the results.
            Ideas submitted against a campaign flow through the same customizable workflow as
            everything else (tune the gates in Hub Settings).
          </p>
        </div>
      </div>

      <div className="card bc-form">
        <h3>Launch a campaign</h3>
        <div className="row">
          <input placeholder="Campaign title — e.g. Cut cost-to-serve in half"
                 value={title} onChange={(e) => setTitle(e.target.value)} />
          <input placeholder="The question you're asking the enterprise"
                 value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button disabled={busy === 'manual' || !title.trim() || !question.trim()}
                  onClick={async () => {
                    setBusy('manual')
                    try {
                      await createChallenge({ title, question })
                      setTitle(''); setQuestion(''); toast('Campaign launched.')
                      load(); onChanged()
                    } finally { setBusy(null) }
                  }}>{busy === 'manual' ? 'Launching…' : 'Launch'}</button>
        </div>
        <div className="row">
          <input placeholder="…or name a trend/competitor and let AI draft the campaign"
                 value={topic} onChange={(e) => setTopic(e.target.value)} />
          <button className="secondary" disabled={busy === 'ai' || !topic.trim()}
                  onClick={async () => {
                    setBusy('ai')
                    try { setDraft(await radarScan(topic, false)) }
                    finally { setBusy(null) }
                  }}>{busy === 'ai' ? 'Researching…' : '✦ AI-draft campaign'}</button>
        </div>
        {draft && !draft.challenge && (
          <div className="plan">
            <p className="small"><strong>Draft:</strong> {draft.draft.challenge_title}{' '}
              <span className="muted small">({draft.generated_by})</span></p>
            <ul className="muted small">{draft.signals.map((sg) => <li key={sg}>{sg}</li>)}</ul>
            <button onClick={async () => {
              setDraft(await radarScan(topic, true)); load(); onChanged()
              toast('Campaign launched with AI starter ideas suggested.')
            }}>Launch this campaign</button>
          </div>
        )}
      </div>

      {challenges.map((c) => {
        const mine = ideas.filter((i) => i.challenge_id === c.id)
        const phase = phaseOf(c, ideas)
        const converted = mine.filter((i) => i.status === 'business_case').length
        const value = mine.reduce((a, i) => a + (i.estimated_annual_benefit
          ?? i.assessment?.estimated_annual_benefit ?? 0), 0)
        return (
          <div key={c.id} className="card">
            <div className="card-header">
              <div>
                <h3>{c.title}</h3>
                <p className="muted small">{c.question}</p>
              </div>
              <span className={c.status === 'active' ? 'badge badge-ok' : 'badge'}>{c.status}</span>
            </div>
            <div className="row" style={{ gap: 0 }}>
              {PHASES.map((p, i) => (
                <span key={p} className={`chip lc-phase-chip ${i < phase ? 'chip-active' : ''} ${i === phase ? 'chain-current chip' : ''}`}>
                  {i <= phase ? '✓ ' : ''}{p}
                </span>
              ))}
            </div>
            <div className="metrics-row">
              <div className="metric" role="button" tabIndex={0} style={{ cursor: 'pointer' }}
                   title="Review these at the gates"
                   onClick={() => window.dispatchEvent(new CustomEvent('ivd-nav', { detail: 'command' }))}>
                <span className="muted small">Ideas →</span><strong>{mine.length}</strong></div>
              <div className="metric"><span className="muted small">In review</span>
                <strong>{mine.filter((i) => !['proposed', 'business_case', 'declined', 'backlog'].includes(i.status)).length}</strong></div>
              <div className="metric"><span className="muted small">Converted to cases</span><strong>{converted}</strong></div>
              <div className="metric"><span className="muted small">Est. value</span><strong>{money(value)}/yr</strong></div>
            </div>
            {c.status === 'active' && (
              <button className="secondary" onClick={async () => {
                if (!window.confirm(`Close "${c.title}"? Results: ${mine.length} ideas, ${converted} case(s), ${money(value)}/yr surfaced.`)) return
                try {
                  await closeChallenge(c.id)
                  toast(`Campaign closed — ${converted} case(s) and ${money(value)}/yr surfaced.`)
                } catch (e) {
                  toast(`Could not close: ${e instanceof Error ? e.message : e}`)
                }
                load(); onChanged()
              }}>Close campaign</button>
            )}
          </div>
        )
      })}
      {challenges.length === 0 && (
        <p className="muted">No campaigns yet — launch the first one above.</p>
      )}
    </section>
  )
}
