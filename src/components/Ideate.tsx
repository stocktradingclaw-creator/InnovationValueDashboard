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
  const [fromSample, setFromSample] = useState(false)
  useEffect(() => {
    fetch(`/api/ideate/studio/latest?kind=${kind}`).then((r) => r.json())
      .then((d) => {
        if (d.run && !out) { setOut(d.run); setTopic(d.run.topic); setFromSample(true) }
      }).catch(() => {})
  }, [kind])
  return (
    <div className="card">
      <h3>{heading}</h3>
      {fromSample && out && (
        <p className="muted small">Showing the latest saved run ("{topic}") — run your own below.</p>
      )}
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
            setOut(await r.json()); setFromSample(false)
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

// Sample futures framework: three causal chains cascading across horizons.
const FUTURES_SAMPLE = {
  topic: 'The autonomous enterprise',
  chains: [
    {
      key: 'agents', label: 'AI agents',
      nodes: [
        'AI agents absorb routine knowledge work',
        'Workflows reorganize around human-AI teams; spans of control widen',
        'Humans govern by exception — operations run autonomously against verified outcomes',
      ],
      explains: [
        'Simply put: software can now do a lot of the routine desk work people do today — reading, sorting, drafting, checking. We can already see this happening, so the near-term move is to adopt it deliberately instead of letting it arrive ad hoc.',
        'Once machines handle the routine work, teams change shape: fewer people supervising more automated work. This is the knock-on effect — not about the tools anymore, but about how the organization is structured around them.',
        'The end state: most operations run themselves, and people step in only when something unusual happens — like a pilot monitoring autopilot. Companies that practice this early will trust it; those that wait will fear it.',
      ],
      narrative: 'The extrapolation is tooling; the second-order effect is organizational; the reimagined state is governance itself changing shape. Companies that rehearse exception-based governance now will not have to retrofit it later.',
      seed: 'Prototype exception-based governance: one process runs autonomously for 30 days, humans review only breaches',
    },
    {
      key: 'value', label: 'Verified outcomes',
      nodes: [
        'Cost scrutiny reshapes vendor stacks and kills activity metrics',
        'Buyers consolidate on partners who can prove impact from data',
        'Value migrates from products to guaranteed, measured outcomes',
      ],
      explains: [
        'Simply put: budgets are tight, so buyers are cutting tools that only show activity (dashboards, reports) and keeping ones that show results. You can see this in renewal conversations today.',
        'The knock-on effect: buyers stop spreading spend across many vendors and concentrate on the few who can prove impact with real data — proof becomes the buying criterion, not features.',
        'The end state: companies stop selling products and start selling guaranteed outcomes — you pay for the result, verified by data, not for the software. Whoever can prove results owns the market.',
      ],
      narrative: 'Near-term budget pressure looks defensive, but its second-order effect is a market that pays for evidence. The reimagined enterprise sells outcomes with a ledger behind them.',
      seed: 'Pick one offering and restate its contract as a measured-outcome guarantee',
    },
    {
      key: 'trust', label: 'Trust & regulation',
      nodes: [
        'Regulation catches up to automated decision-making',
        'Auditability becomes a market requirement, not a compliance chore',
        'Trust infrastructure — provable, tamper-evident value — becomes the moat',
      ],
      explains: [
        'Simply put: governments are writing rules about decisions made by software — who is accountable, what must be explainable. This is already in motion.',
        'The knock-on effect: being able to show HOW a decision was made stops being paperwork and becomes something customers demand before they buy — like security certifications today.',
        'The end state: the companies allowed to automate the most will be the ones with the best audit trails. Provable trust becomes the competitive moat, not the algorithm.',
      ],
      narrative: 'What starts as compliance cost compounds into advantage: the firms with audit-grade decision trails will be the only ones allowed to automate aggressively.',
      seed: 'Inventory our automated decisions and rank them by audit-readiness',
    },
  ],
}

const HORIZON_HEADS: [string, string, string][] = [
  ['1–3y', 'Extrapolate', 'lc-tone-idea'],
  ['3–7y', 'Second-order', 'lc-tone-case'],
  ['7–15y', 'Reimagine', 'lc-tone-value'],
]

function FuturesMap() {
  const [sel, setSel] = useState<{ key: string; col: number } | null>(null)
  const chain = FUTURES_SAMPLE.chains.find((c) => c.key === sel?.key)
  return (
    <div className="card">
      <div className="card-header">
        <h3>How the horizons connect — sample framework: {FUTURES_SAMPLE.topic}</h3>
        <span className="muted small">click a card to trace its causal chain</span>
      </div>
      <div className="fmap">
        {HORIZON_HEADS.map(([years, label, tone], col) => (
          <div key={label} className="fmap-col">
            <div className={`lc-phase-head ${tone}`}>
              <strong>{label}</strong><span className="muted small">{years}</span>
            </div>
            {FUTURES_SAMPLE.chains.map((c) => (
              <button key={c.key} type="button"
                      className={`fmap-node ${sel?.key === c.key ? (sel.col === col ? 'fmap-hot' : 'fmap-warm') : sel ? 'fmap-dim' : ''}`}
                      onClick={() => setSel(sel?.key === c.key && sel.col === col ? null : { key: c.key, col })}
                      title={c.label}>
                <span className="small">{c.nodes[col]}</span>
                {col < 2 && <span className="fmap-arrow" aria-hidden="true">➜</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
      <p className="small fmap-caption" aria-live="polite">
        {chain && sel ? (
          <>
            <strong>{HORIZON_HEADS[sel.col][1]} · {chain.label}:</strong>{' '}
            {(chain as unknown as { explains: string[] }).explains[sel.col]}{' '}
            {sel.col < 2 && <em className="muted">Next in the chain: "{chain.nodes[sel.col + 1]}". </em>}
            <button type="button" className="chip"
                    onClick={() => seedIdea(chain.seed, 'ideate-futures')}>
              + capture: {chain.seed.slice(0, 60)}…
            </button>
          </>
        ) : (
          'Each row is one force traced left to right: what we can already see, what it does to the system next, and the future it implies. Click any card to read the chain — then run your own topic below.'
        )}
      </p>
    </div>
  )
}

function MaturityStudioWithDeltas() {
  const [lastTopic, setLastTopic] = useState('')
  useEffect(() => {
    fetch('/api/ideate/studio/latest?kind=maturity').then((r) => r.json())
      .then((d) => { if (d.run) setLastTopic(d.run.topic) }).catch(() => {})
  }, [])
  return (
    <>
      <Studio kind="maturity" heading="Assess a topic"
              blurb="Five-dimension read with level ratings; re-assess the same topic later and the deltas appear below." />
      {lastTopic && <MaturityDeltas topic={lastTopic} />}
    </>
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

function BreakthroughConcepts() {
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [out, setOut] = useState<{ concepts: { name: string; narrative: string; types_combined: number[]; target_customer: string; revenue_logic: string; orthodoxy_broken: string; impact: number; differentiation: number; feasibility: number; fit: number }[]; recommended: string[]; recommendation_reasoning: string; experiments: Record<string, string>[]; generated_by: string } | null>(null)
  return (
    <div className="card">
      <h3>Breakthrough concepts</h3>
      <p className="muted small">Concepts that combine three or more types — scored 1–5 on impact,
        differentiation, feasibility, and fit, each with the experiment that could kill it.</p>
      <div className="row">
        <input placeholder="Business context — what are we building concepts for?"
               value={topic} onChange={(e) => setTopic(e.target.value)} />
        <button disabled={busy || !topic.trim()} onClick={async () => {
          setBusy(true)
          try {
            const r = await fetch('/api/ideate/tentypes-concepts', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ kind: 'ten_types', topic }) })
            setOut(await r.json())
          } finally { setBusy(false) }
        }}>{busy ? 'Combining types…' : '✦ Generate concepts'}</button>
      </div>
      {out && (
        <div className="plan">
          {out.concepts.map((c) => {
            const total = c.impact + c.differentiation + c.feasibility + c.fit
            const rec = out.recommended.includes(c.name)
            return (
              <div key={c.name} className={`card ${rec ? 'attention-card' : ''}`} style={{ marginBottom: '0.6rem' }}>
                <div className="card-header">
                  <h3>{rec ? '★ ' : ''}{c.name}</h3>
                  <span className="row">{c.types_combined.map((t) => (
                    <span key={t} title={Object.keys(TYPE_NUM).find((k) => TYPE_NUM[k] === t)}
                          className={`pill tt-chip tt-${t <= 4 ? 'config' : t <= 6 ? 'offer' : 'exp'}`}>{t}</span>
                  ))}
                    <span className="badge">{total}/20</span></span>
                </div>
                <p className="small">{c.narrative}</p>
                <p className="muted small">For {c.target_customer} · {c.revenue_logic} ·
                  breaks: "{c.orthodoxy_broken}" · impact {c.impact} · diff {c.differentiation} ·
                  feas {c.feasibility} · fit {c.fit}</p>
                <button className="chip" onClick={() => seedIdea(c.name + ': ' + c.narrative.slice(0, 90), 'ideate-tentypes')}>+ capture as idea</button>
              </div>
            )
          })}
          <p className="small pending-action"><strong>Recommended:</strong> {out.recommendation_reasoning}</p>
          {out.experiments.map((e0, i) => (
            <p key={i} className="muted small">🧪 <strong>{e0.concept}:</strong> riskiest assumption —
              {e0.riskiest_assumption}. {e0.experiment} ({e0.duration_days}d). Kill metric: {e0.kill_metric}</p>
          ))}
        </div>
      )}
    </div>
  )
}

const TYPE_CATEGORY: Record<string, string> = {
  'Profit Model': 'config', Network: 'config', Structure: 'config', Process: 'config',
  'Product Performance': 'offer', 'Product System': 'offer',
  Service: 'exp', Channel: 'exp', Brand: 'exp', 'Customer Engagement': 'exp',
}
const TYPE_NUM: Record<string, number> = {
  'Profit Model': 1, Network: 2, Structure: 3, Process: 4, 'Product Performance': 5,
  'Product System': 6, Service: 7, Channel: 8, Brand: 9, 'Customer Engagement': 10,
}

function TenTypesMirror() {
  const [m, setM] = useState<{ grid: { type: string; about: string; count: number; examples: string[] }[]; headline: string; empty_types: string[] } | null>(null)
  useEffect(() => { fetch('/api/ideate/tentypes-mirror').then((r) => r.json()).then(setM).catch(() => {}) }, [])
  if (!m) return null
  return (
    <div className="card">
      <h3>Your portfolio in the mirror</h3>
      <p className="small"><strong>{m.headline}</strong></p>
      <p className="muted small">
        <span className="tt-key tt-config">■</span> Configuration (1–4) ·{' '}
        <span className="tt-key tt-offer">■</span> Offering (5–6) ·{' '}
        <span className="tt-key tt-exp">■</span> Experience (7–10)
      </p>
      <div className="tentype-grid">
        {m.grid.map((g) => (
          <div key={g.type} className={`card tentype-card tt-${TYPE_CATEGORY[g.type]} ${g.count === 0 ? 'tentype-empty' : ''}`}>
            <p className="small"><span className="tt-num">{TYPE_NUM[g.type]}</span> <strong>{g.type}</strong>{' '}
              {g.count > 0
                ? <span className="pill act-approve">{g.count}</span>
                : <span className="pill act-verify">empty</span>}</p>
            <p className="muted small">{g.count > 0 ? g.examples.join(' · ') : g.about}</p>
            {g.count === 0 && (
              <button className="chip" onClick={() =>
                seedIdea(`Explore a ${g.type} play: change ${g.about} instead of the product`, 'ideate-tentypes')}>
                + seed a {g.type} idea
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

interface CompReport {
  generated_by: string
  executive_summary: string[]; top_recommendation: string
  market_overview: string; trends: string[]
  comparison_matrix_criteria: string[]
  comparison_matrix: { name: string; scores: { criterion: string; rating: string; justification: string; confidence: string }[] }[]
  positioning_x_axis: string; positioning_y_axis: string
  positioning: { company: string; x: number; y: number }[]; white_space: string
  swot_strengths: string[]; swot_weaknesses: string[]; swot_opportunities: string[]; swot_threats: string[]
  recommendations: { title: string; based_on_finding: string; impact: string; effort: string; priority: number }[]
  thin_areas: string[]; suggested_research: string[]
}

let _repCache: CompReport | null = null

function CompetitiveReport() {
  const [form, setForm] = useState({ product: '', description: '', segment: '', audience: 'leadership', decision: '', competitors: '' })
  const [busy, setBusy] = useState(false)
  const [stage, setStage] = useState('')
  const [rep, setRepState] = useState<CompReport | null>(_repCache)
  const setRep = (r: CompReport | null) => { _repCache = r; setRepState(r) }
  const [saved, setSaved] = useState<{ id: number; topic: string; created_at: string }[]>([])
  useEffect(() => {
    fetch('/api/ideate/competitive-reports').then((r) => r.json()).then(async (d) => {
      setSaved(d.reports)
      if (!rep && d.reports.length > 0) {
        const latest = await (await fetch(`/api/ideate/competitive-reports/${d.reports[0].id}`)).json()
        setRep(latest); setForm((f) => ({ ...f, product: d.reports[0].topic }))
      }
    }).catch(() => {})
  }, [])
  const generate = async () => {
    setBusy(true); setRep(null)
    const stages = ['Researching competitors…', 'Scoring the comparison matrix…', 'Mapping positioning & white space…', 'Writing recommendations…']
    let i = 0
    const t = window.setInterval(() => setStage(stages[Math.min(i++, stages.length - 1)]), 1400)
    try {
      const r = await fetch('/api/ideate/competitive-report', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, competitors: form.competitors.split(',').map((c) => c.trim()).filter(Boolean) }),
      })
      if (!r.ok) throw new Error((await r.json()).detail ?? 'generation failed')
      setRep(await r.json())
    } catch (e) { toast(e instanceof Error ? e.message : String(e)) }
    finally { window.clearInterval(t); setBusy(false); setStage('') }
  }
  const rateClass = (r: string) => r === 'strong' ? 'act-approve' : r === 'weak' ? 'act-intervene' : 'act-verify'
  return (
    <div className="card">
      <h3>Company vs peers — full competitive report</h3>
      <p className="muted small">Compare your company against peer companies — strategy, innovation posture, and
        position — in a structured, confidence-labeled report: matrix, positioning map, SWOT, and prioritized moves.</p>
      <div className="row">
        <input placeholder="Company name or industry — that's all you need *"
               value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })}
               onKeyDown={(e) => e.key === 'Enter' && form.product.trim() && !busy && generate()} />
        <button disabled={busy || !form.product.trim()} onClick={generate}>
          {busy ? stage || 'Working…' : '✦ Generate report'}
        </button>
      </div>
      <p className="muted small">
        The engine researches and infers the rest — what the company does, its market, the five
        closest peers (justified), and the innovation-strategy framing.
      </p>
      {saved.length > 0 && !rep && (
        <p className="muted small">Saved: {saved.slice(0, 5).map((s0) => (
          <button key={s0.id} className="chip" onClick={async () => {
            setRep(await (await fetch(`/api/ideate/competitive-reports/${s0.id}`)).json())
          }}>{s0.topic} · {s0.created_at.slice(0, 10)}</button>
        ))}</p>
      )}
      {rep && (
        <div className="plan">
          <h4>Executive summary <span className="muted small">({rep.generated_by})</span></h4>
          <ul className="small">{rep.executive_summary.map((x) => <li key={x}>{x}</li>)}</ul>
          <p className="small pending-action"><strong>Top recommendation:</strong> {rep.top_recommendation}</p>
          <h4>Comparison matrix</h4>
          <table className="kpi-table">
            <thead><tr><th>Criterion</th>{rep.comparison_matrix.map((c) => <th key={c.name}>{c.name}</th>)}</tr></thead>
            <tbody>
              {rep.comparison_matrix_criteria.map((crit, i) => (
                <tr key={crit}><td><strong>{crit}</strong></td>
                  {rep.comparison_matrix.map((c) => {
                    const sc = c.scores[i]
                    return <td key={c.name}><span className={`pill ${rateClass(sc.rating)}`}
                      title={`${sc.justification} [${sc.confidence}]`}>{sc.rating}</span></td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Hover any rating for its justification and confidence
            (fact / inference / assumption).</p>
          <h4>Positioning — {rep.positioning_x_axis} vs {rep.positioning_y_axis}</h4>
          <div className="matrix" style={{ height: 220 }}>
            {rep.positioning.map((pp) => (
              <span key={pp.company} className="dot dot-strategic_bet"
                    style={{ left: `${(pp.x + 1) * 50}%`, top: `${(1 - pp.y) * 50}%`, width: 12, height: 12 }}
                    title={pp.company} />
            ))}
            {rep.positioning.map((pp) => (
              <span key={`${pp.company}-l`} className="small" style={{ position: 'absolute',
                left: `${(pp.x + 1) * 50}%`, top: `calc(${(1 - pp.y) * 50}% + 8px)`, transform: 'translateX(-50%)' }}>
                {pp.company}</span>
            ))}
          </div>
          <p className="small"><strong>White space:</strong> {rep.white_space}</p>
          <h4>SWOT</h4>
          <div className="two-col">
            <div><strong className="small">Strengths</strong><ul className="small">{rep.swot_strengths.map((x) => <li key={x}>{x}</li>)}</ul>
              <strong className="small">Opportunities</strong><ul className="small">{rep.swot_opportunities.map((x) => <li key={x}>{x}</li>)}</ul></div>
            <div><strong className="small">Weaknesses</strong><ul className="small">{rep.swot_weaknesses.map((x) => <li key={x}>{x}</li>)}</ul>
              <strong className="small">Threats</strong><ul className="small">{rep.swot_threats.map((x) => <li key={x}>{x}</li>)}</ul></div>
          </div>
          <h4>Prioritized moves</h4>
          {rep.recommendations.sort((a, b) => a.priority - b.priority).map((r0) => (
            <div key={r0.title} className="decision-row">
              <span className="pill act-approve">#{r0.priority}</span>
              <span><strong>{r0.title}</strong> <span className="muted small">{r0.based_on_finding} ·
                impact {r0.impact} · effort {r0.effort}</span></span>
              <button className="chip" onClick={() => seedIdea(r0.title, 'ideate-competitive')}>+ idea</button>
            </div>
          ))}
          <p className="muted small"><strong>Thin areas:</strong> {rep.thin_areas.join(' · ')} —{' '}
            <strong>firm up with:</strong> {rep.suggested_research.join(' · ')}</p>
        </div>
      )}
    </div>
  )
}

function Watchlist() {
  const [w, setW] = useState<{ topic: string; last_scanned: string; scans: number; changed_since_last: string[]; latest: StudioOut }[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const load = () => fetch('/api/ideate/watchlist').then((r) => r.json()).then((d) => setW(d.watchlist)).catch(() => {})
  useEffect(() => { load() }, [])
  if (w.length === 0) return null
  return (
    <div className="card">
      <h3>Watchlist</h3>
      <p className="muted small">Competitors and markets you track — re-scan any time; changes since your last scan are called out.</p>
      {w.map((c) => (
        <div key={c.topic} className="card" style={{ marginBottom: '0.6rem' }}>
          <div className="card-header">
            <div>
              <strong>{c.topic}</strong>
              <p className="muted small">last scanned {c.last_scanned.slice(0, 10)} · {c.scans} scan(s)</p>
            </div>
            <button className="secondary" disabled={busy === c.topic} onClick={async () => {
              setBusy(c.topic)
              try {
                await fetch('/api/ideate/studio', { method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ kind: 'competitive', topic: c.topic }) })
                await load(); toast(`Re-scanned ${c.topic}.`)
              } finally { setBusy(null) }
            }}>{busy === c.topic ? 'Scanning…' : 'Re-scan'}</button>
          </div>
          {c.changed_since_last.length > 0 && (
            <p className="small pending-action">Changed since last scan: {c.changed_since_last.join(' · ')}</p>
          )}
          <div className="row">
            {c.latest.idea_seeds.slice(0, 2).map((seed) => (
              <button key={seed} className="chip" onClick={() => seedIdea(seed, 'ideate-competitive')}>+ {seed.slice(0, 55)}</button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function MaturityDeltas({ topic }: { topic: string }) {
  const [h, setH] = useState<{ deltas: Record<string, number>; assessments: unknown[] } | null>(null)
  useEffect(() => {
    if (!topic) return
    fetch(`/api/ideate/maturity-history?topic=${encodeURIComponent(topic)}`)
      .then((r) => r.json()).then(setH).catch(() => {})
  }, [topic])
  if (!h || h.assessments.length < 2) return null
  return (
    <p className="small pending-action">
      Movement since your previous assessment:{' '}
      {Object.entries(h.deltas).map(([d, v]) =>
        `${d} ${v > 0 ? `▲ +${v}` : v < 0 ? `▼ ${v}` : '—'}`).join(' · ')}
    </p>
  )
}

function SessionHistory() {
  const [ss, setSs] = useState<{ session: string; ideas: number; qualified: number; est_value: number }[]>([])
  useEffect(() => { fetch('/api/ideate/sessions').then((r) => r.json()).then((d) => setSs(d.sessions)).catch(() => {}) }, [])
  if (ss.length === 0) return null
  return (
    <div className="card">
      <h3>Past sessions</h3>
      {ss.map((x) => (
        <div key={x.session} className="decision-row">
          <span className="pill act-approve">{x.ideas} ideas</span>
          <span><strong>{x.session}</strong>{' '}
            <span className="muted small">{x.qualified} qualified · est. value captured</span></span>
        </div>
      ))}
    </div>
  )
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
      {view === 'futures' && <FuturesMap />}
      {view === 'futures' && (
        <Studio kind="futures" withHorizon heading="Run a futures scan"
                blurb="Signals → implications → a reimagined future state, with idea seeds to rehearse it now." />
      )}
      {view === 'competitive' && <CompetitiveReport />}
      {view === 'competitive' && <Watchlist />}
      {view === 'competitive' && (
        <Studio kind="competitive" heading="Analyze a competitor or market"
                blurb="Name a competitor, market, or move. Gaps become capture-ready idea seeds." />
      )}
      {view === 'maturity' && <MaturityStudioWithDeltas />}
      {view === 'maturity' && false && (
        <Studio kind="maturity" heading="Assess a topic"
                blurb="Five-dimension read with level ratings and the next-level requirement per dimension." />
      )}
      {view === 'workshops' && <MuralStudio onChanged={onChanged} />}
      {view === 'workshops' && <SessionHistory />}
      {view === 'tentypes' && <TenTypesMirror />}
      {view === 'tentypes' && <BreakthroughConcepts />}
      {view === 'tentypes' && (
        <Studio kind="ten_types" heading="Scan all ten types"
                blurb="One opportunity prompt per type, profit model through customer engagement." />
      )}
    </section>
  )
}
