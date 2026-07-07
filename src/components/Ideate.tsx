import { useEffect, useState } from 'react'
import { toast } from '../api'

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
          <div className={kind === 'ten_types' ? 'tentype-grid' : undefined}>
          {out.items.map((it) => {
            const lvl = it.title.match(/level (\d)\/5/)
            return (
              <div key={it.title} className={kind === 'ten_types' ? 'card tentype-card' : 'studio-item'}>
                <p className="small"><strong>{it.title}</strong>{' '}
                  <span className="muted">{it.detail}</span></p>
                {lvl && (
                  <div className="funnel-track thin">
                    <div className="funnel-bar stage-committed"
                         style={{ width: `${(Number(lvl[1]) / 5) * 100}%` }} />
                  </div>
                )}
              </div>
            )
          })}
          </div>
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

export type IdeateView = 'futures' | 'competitive' | 'maturity' | 'workshops' | 'tentypes'

const PAGES: Record<IdeateView, { title: string; intro: string }> = {
  futures: {
    title: 'Futures studio',
    intro: "Reimagine, don't extrapolate — Frank Diana's discipline across three timeframes: " +
           'extrapolate signals (1–3y), trace second-order effects (3–7y), and reimagine the ' +
           'future state (7–15y). Run the same topic at multiple horizons and compare.',
  },
  competitive: {
    title: 'Competitive analysis',
    intro: 'Strengths, recent moves, and the gaps you can exploit — researched live with web ' +
           'search when AI is configured. Every gap becomes an idea seed you can capture.',
  },
  maturity: {
    title: 'Maturity assessment',
    intro: 'A high-level, directional read of where you stand on a key industry topic across ' +
           'five dimensions — strategy, data, governance, talent, technology — and what moving ' +
           'up a level would take. Validate in a workshop; capture the moves as ideas.',
  },
  workshops: {
    title: 'Design-thinking workshops',
    intro: 'Run team ideation in Mural with the preset templates below, then ingest the session ' +
           'export — every sticky note becomes a real, triaged idea attributed to the session.',
  },
  tentypes: {
    title: 'Ten Types of Innovation',
    intro: "Larry Keeley's lens: most companies over-invest in product performance while the " +
           'defensible plays combine three or more types. Scan any topic across all ten.',
  },
}

export default function Ideate({ view, onChanged }: { view: IdeateView; onChanged: () => void }) {
  const page = PAGES[view]
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>{page.title}</h2>
          <p className="muted">{page.intro}</p>
        </div>
      </div>
      {view === 'futures' && (
        <Studio kind="futures" withHorizon heading="Run a futures scan"
                blurb="Signals → implications → a reimagined future state, with idea seeds to rehearse it now." />
      )}
      {view === 'competitive' && (
        <Studio kind="competitive" heading="Analyze a competitor or market"
                blurb="Name a competitor, market, or move. Gaps become capture-ready idea seeds." />
      )}
      {view === 'maturity' && (
        <Studio kind="maturity" heading="Assess a topic"
                blurb="Five-dimension read with level ratings and the next-level requirement per dimension." />
      )}
      {view === 'workshops' && <MuralStudio onChanged={onChanged} />}
      {view === 'tentypes' && (
        <Studio kind="ten_types" heading="Scan all ten types"
                blurb="One opportunity prompt per type, profit model through customer engagement." />
      )}
    </section>
  )
}
