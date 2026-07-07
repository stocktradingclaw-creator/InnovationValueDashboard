import { useEffect, useState } from 'react'
import { money, toast } from '../api'
import type { Opportunity } from '../types'

interface StudioOut {
  narrative: string
  items: { title: string; detail: string }[]
  idea_seeds: string[]
  generated_by: string
}

function seedIdea(title: string, source: string) {
  return fetch('/api/integrations/capture', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, source, submitter: localStorage.getItem('ivd_user') || undefined }),
  }).then((r) => { if (!r.ok) throw new Error('capture failed'); toast(`Captured as an idea: "${title.slice(0, 60)}…"`) })
}

function Studio({ kind, heading, blurb, withHorizon }: {
  kind: string; heading: string; blurb: string; withHorizon?: boolean
}) {
  const [topic, setTopic] = useState('')
  const [horizon, setHorizon] = useState('3-7y')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<StudioOut | null>(null)
  return (
    <div className="card">
      <h3>{heading}</h3>
      <p className="muted small">{blurb}</p>
      <div className="row">
        <input placeholder="Topic — market, capability, competitor, or industry question"
               value={topic} onChange={(e) => setTopic(e.target.value)} />
        {withHorizon && (
          <select value={horizon} onChange={(e) => setHorizon(e.target.value)} aria-label="Horizon">
            <option value="1-3y">1–3 years (extrapolate)</option>
            <option value="3-7y">3–7 years (second-order)</option>
            <option value="7-15y">7–15 years (reimagine)</option>
          </select>
        )}
        <button disabled={busy || !topic.trim()} onClick={async () => {
          setBusy(true)
          try {
            const r = await fetch('/api/ideate/studio', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ kind, topic, horizon }),
            })
            setOut(await r.json())
          } finally { setBusy(false) }
        }}>{busy ? 'Working…' : '✦ Run'}</button>
      </div>
      {out && (
        <div className="plan">
          <p className="small"><strong>{out.narrative}</strong>{' '}
            <span className="muted small">({out.generated_by})</span></p>
          {out.items.map((it) => (
            <p key={it.title} className="small"><strong>{it.title}</strong>{' '}
              <span className="muted">{it.detail}</span></p>
          ))}
          <div className="row">
            {out.idea_seeds.map((seed) => (
              <button key={seed} className="chip" onClick={() => seedIdea(seed, `ideate-${kind}`)}>
                + {seed.slice(0, 70)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MuralStudio({ onChanged }: { onChanged: () => void }) {
  const [templates, setTemplates] = useState<{ name: string; url: string }[]>([])
  const [how, setHow] = useState('')
  const [text, setText] = useState('')
  const [session, setSession] = useState('')
  const [busy, setBusy] = useState(false)
  const [created, setCreated] = useState<{ id: string; title: string; recommendation: string }[]>([])
  useEffect(() => {
    fetch('/api/ideate/mural-templates').then((r) => r.json())
      .then((d) => { setTemplates(d.templates); setHow(d.how) }).catch(() => {})
  }, [])
  return (
    <div className="card">
      <h3>Team design-thinking session (Mural)</h3>
      <p className="muted small">{how}</p>
      <div className="row">
        {templates.map((t) => (
          <a key={t.name} className="chip" href={t.url} target="_blank" rel="noreferrer">
            {t.name} ↗
          </a>
        ))}
      </div>
      <textarea rows={4} placeholder={'Paste the session export here — one sticky note per line…'}
                value={text} onChange={(e) => setText(e.target.value)} />
      <div className="row">
        <input placeholder="Session name (optional)" value={session}
               onChange={(e) => setSession(e.target.value)} />
        <button disabled={busy || text.trim().length < 12} onClick={async () => {
          setBusy(true)
          try {
            const r = await fetch('/api/ideate/mural-ingest', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text, session_name: session || undefined,
                                     facilitator: localStorage.getItem('ivd_user') || undefined }),
            })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail ?? 'ingest failed')
            setCreated(d.created); setText('')
            toast(`${d.created.length} sticky notes became triaged ideas.`)
            onChanged()
          } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
          finally { setBusy(false) }
        }}>{busy ? 'Ingesting…' : 'Ingest session → ideas'}</button>
      </div>
      {created.length > 0 && (
        <p className="muted small">
          Created: {created.map((c) => `${c.title.slice(0, 40)} (${c.recommendation})`).join(' · ')}
        </p>
      )}
    </div>
  )
}

export default function Ideate({ opportunities, onChanged }: {
  opportunities: Opportunity[]; onChanged: () => void
}) {
  const top = opportunities.slice(0, 5)
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Ideate</h2>
          <p className="muted">
            Where ideas come from: opportunities detected in your own data, futures thinking,
            competitive gaps, maturity honesty, team sessions, and the Ten Types lens — every
            output one click from becoming a triaged idea.
          </p>
        </div>
      </div>

      {top.length > 0 && (
        <div className="card">
          <h3>Detected in your data — start here</h3>
          <p className="muted small">The engine already found these in your integrated sources.</p>
          {top.map((o) => (
            <div key={o.id} className="decision-row">
              <span className="savings small">{money(o.estimated_annual_savings)}/yr</span>
              <span><strong>{o.title}</strong> <span className="muted small">{o.category}</span></span>
              <button className="chip" onClick={() => seedIdea(o.title, 'ideate-detected')}>+ idea</button>
            </div>
          ))}
        </div>
      )}

      <Studio kind="futures" withHorizon heading="Futures studio — reimagine, don't extrapolate"
              blurb="Frank Diana-style rethinking across timeframes: signals, implications, and a reimagined future state, with idea seeds to rehearse it now." />
      <Studio kind="competitive" heading="Competitive analysis"
              blurb="Strengths, recent moves, and the gaps you can exploit — researched live when AI is configured." />
      <Studio kind="maturity" heading="Maturity assessment"
              blurb="A high-level, directional read of where you stand on a key industry topic — and what moving up a level would take." />
      <MuralStudio onChanged={onChanged} />
      <Studio kind="ten_types" heading="Ten Types of Innovation (Keeley)"
              blurb="AI scans all ten types — profit model to customer engagement — because innovation compounds when you combine types beyond the product." />
    </section>
  )
}
