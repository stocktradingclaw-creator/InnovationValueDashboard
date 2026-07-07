import { useEffect, useState } from 'react'
import { exportUrl, toast } from '../api'

type Section = 'overview' | 'campaigns' | 'assessment' | 'results' | 'quadrant' | 'roadmap'
interface DimResult {
  id: string; name: string; iso_56001_clauses: string[]; score: number | null
  band: string | null; gap: number; gap_pair: [string, string] | null; gap_flagged: boolean
  by_level: Record<string, { n: number; score: number | null; suppressed: boolean }>
}
interface Results {
  campaign: { id: number; name: string; is_anonymous: number }
  config: { readiness: number; gap_threshold: number; min_segment_n: number }
  dimensions: DimResult[]; composite: number | null; band: string | null
  flagged_gaps: { name: string; gap: number; levels: [string, string] }[]
  response_rate: { invited: number; completed: number; responses: number }; note: string
}

function Radar({ dims, readiness }: { dims: DimResult[]; readiness: number }) {
  const N = dims.length, R = 88, CX = 130, CY = 108
  const pt = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / N - Math.PI / 2
    return `${CX + Math.cos(a) * (v / 100) * R},${CY + Math.sin(a) * (v / 100) * R}`
  }
  return (
    <svg viewBox="0 0 320 225" role="img" aria-label="Dimension scores radar">
      {[25, 50, 75, 100].map((r) => (
        <polygon key={r} points={dims.map((_, i) => pt(i, r)).join(' ')} fill="none"
                 stroke="var(--border)" strokeWidth="0.6" />
      ))}
      <polygon points={dims.map((_, i) => pt(i, readiness)).join(' ')} fill="none"
               stroke="var(--info)" strokeWidth="1.2" strokeDasharray="4 3" />
      <polygon points={dims.map((d, i) => pt(i, d.score ?? 0)).join(' ')}
               fill="rgba(76,195,138,0.15)" stroke="var(--accent)" strokeWidth="2" />
      {dims.map((d, i) => {
        const [x, y] = pt(i, 112).split(',').map(Number)
        return <text key={d.id} x={x} y={y} textAnchor="middle"
                     style={{ fill: 'var(--muted)', fontSize: 7 }}>{d.id}</text>
      })}
    </svg>
  )
}

export default function Audit() {
  const [sec, setSec] = useState<Section>('overview')
  const [cid, setCid] = useState<number | null>(null)
  const [camps, setCamps] = useState<{ id: number; name: string }[]>([])
  const [res, setRes] = useState<Results | null>(null)
  const [level, setLevel] = useState('practitioner')
  const [qs, setQs] = useState<{ id: string; dimension: string; statement: string; role_specific?: boolean; anchors: Record<string, string> }[]>([])
  const [rubric, setRubric] = useState<Record<string, string>>({})
  const [answers, setAnswers] = useState<Record<string, number | 'na'>>({})
  const [quad, setQuad] = useState<{ points: { campaign: string; maturity: number; value: number }[]; maturity_threshold: number; value_threshold: number; labels: Record<string, string> } | null>(null)
  const [items, setItems] = useState<{ id: number; title: string; description: string; horizon: string; status: string; priority: number; owner: string | null; dimension: string; template_id: string }[]>([])

  const load = () => fetch('/api/audit/campaigns').then((r) => r.json()).then((d) => {
    setCamps(d.campaigns)
    const id = cid ?? d.campaigns[d.campaigns.length - 1]?.id
    if (id) {
      setCid(id)
      fetch(`/api/audit/campaigns/${id}/results`).then((r) => r.json()).then(setRes)
      fetch(`/api/audit/campaigns/${id}/roadmap`).then((r) => r.json()).then((x) => setItems(x.items))
    }
  }).catch(() => {})
  useEffect(() => { load() }, [cid])
  useEffect(() => {
    fetch(`/api/audit/questions?level=${level}`).then((r) => r.json())
      .then((d) => { setQs(d.questions); setRubric(d.rubric) }).catch(() => {})
  }, [level])
  useEffect(() => { fetch('/api/audit/quadrant').then((r) => r.json()).then(setQuad).catch(() => {}) }, [res])

  const SECTIONS: [Section, string][] = [['overview', 'Overview'], ['campaigns', 'Campaigns'],
    ['assessment', 'My Assessment'], ['results', 'Results & Gaps'],
    ['quadrant', 'Maturity × Value'], ['roadmap', 'Roadmap']]
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Innovation Management Audit</h2>
          <p className="muted">Two layers: a survey-based capability audit across eight
            dimensions, and a Value Realization Index from this dashboard's own outcome
            metrics — their intersection tells you whether capability is converting to value.</p>
        </div>
        <select value={cid ?? ''} onChange={(e) => setCid(Number(e.target.value))} aria-label="Audit campaign">
          {camps.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <nav className="row" aria-label="Audit sections">
        {SECTIONS.map(([k, label]) => (
          <button key={k} className={sec === k ? 'chip chip-active' : 'chip'}
                  onClick={() => setSec(k)}>{label}</button>
        ))}
      </nav>

      {sec === 'overview' && res && (
        <div className="card">
          <div className="metrics-row">
            <div className="metric"><span className="muted small">Composite maturity</span>
              <strong>{res.composite ?? '—'}/100</strong></div>
            <div className="metric"><span className="muted small">Band</span>
              <strong>{res.band ?? '—'}</strong> <span className="muted small">(ready at {res.config.readiness})</span></div>
            <div className="metric"><span className="muted small">Responses</span>
              <strong>{res.response_rate.responses}</strong> <span className="muted small">
                of {res.response_rate.invited} invited</span></div>
            <div className="metric"><span className="muted small">Flagged perception gaps</span>
              <strong>{res.flagged_gaps.length}</strong></div>
          </div>
          {res.flagged_gaps.map((g) => (
            <p key={g.name} className="small pending-action">
              {g.name}: {g.levels[0]} and {g.levels[1]} diverge by {g.gap} points — see the
              alignment item on the Roadmap.</p>
          ))}
        </div>
      )}

      {sec === 'campaigns' && (
        <div className="card">
          <h3>Audit campaigns <span className="muted small">(admin)</span></h3>
          <p className="muted small">Anonymous campaigns never store identity with responses;
            completion tracking stays separate. Segments under {res?.config.min_segment_n ?? 3}
            {' '}respondents are suppressed in every breakdown.</p>
          <button onClick={async () => {
            const name = window.prompt('Campaign name (e.g. Annual audit 2027)')
            if (!name) return
            await fetch('/api/audit/campaigns', { method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name, is_anonymous: window.confirm('Anonymous campaign?') }) })
            toast('Campaign created — invite respondents via the API or seed.'); load()
          }}>+ New campaign</button>
        </div>
      )}

      {sec === 'assessment' && (
        <div className="card">
          <div className="card-header">
            <h3>My assessment</h3>
            <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Your level">
              {['executive', 'management', 'practitioner'].map((l) => <option key={l}>{l}</option>)}
            </select>
          </div>
          <p className="muted small">Scored 0–4: {Object.entries(rubric).map(([k, v]) => `${k}=${v}`).join(' · ')}.
            {' '}Questions are tailored to your role — the {qs.length} you see are asked from your vantage point. "N/A" answers are excluded
            from scoring.</p>
          {qs.map((q) => (
            <div key={q.id} className="card" style={{ marginBottom: '0.5rem' }}>
              <p className="small"><strong>{q.dimension}</strong>
                {q.role_specific && <span className="pill act-approve" title="Phrased for your role — other levels are asked this from their own vantage point"> your view</span>}
                {' '}· {q.statement}</p>
              <div className="row">
                {[0, 1, 2, 3, 4].map((v) => (
                  <button key={v} className={answers[q.id] === v ? 'chip chip-active' : 'chip'}
                          title={q.anchors[String(v)]}
                          onClick={() => setAnswers({ ...answers, [q.id]: v })}>{v}</button>
                ))}
                <button className={answers[q.id] === 'na' ? 'chip chip-active' : 'chip'}
                        onClick={() => setAnswers({ ...answers, [q.id]: 'na' })}>N/A</button>
              </div>
            </div>
          ))}
          <button disabled={Object.keys(answers).length < qs.length} onClick={async () => {
            const r = await fetch(`/api/audit/campaigns/${cid}/responses`, { method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ level, org_unit: '',
                respondent: localStorage.getItem('ivd_user') || undefined,
                items: qs.map((q) => ({ question: q.id,
                  score: answers[q.id] === 'na' ? 0 : answers[q.id],
                  is_na: answers[q.id] === 'na' })) }) })
            if (!r.ok) {
              const d = await r.json().catch(() => ({}))
              toast(`Submit failed: ${d.detail ?? r.statusText} — your answers are preserved.`)
              return
            }
            toast('Assessment submitted — thank you.')
            setAnswers({}); load()
          }}>Submit assessment ({Object.keys(answers).length}/{qs.length} answered)</button>
        </div>
      )}

      {sec === 'results' && res && (
        <>
          <div className="card"><h3>Dimension radar</h3>
            <Radar dims={res.dimensions} readiness={res.config.readiness} />
            <p className="muted small">Green: calibrated composite per dimension. Dashed blue:
              readiness threshold ({res.config.readiness}).</p></div>
          <div className="card">
            <h3>Perception gaps by level</h3>
            <table className="kpi-table">
              <thead><tr><th>Dimension (ISO 56001)</th><th className="num">exec</th>
                <th className="num">mgmt</th><th className="num">pract</th>
                <th className="num">max gap</th><th>flag</th></tr></thead>
              <tbody>
                {res.dimensions.map((d) => (
                  <tr key={d.id}>
                    <td><strong>{d.name}</strong>
                      <div className="muted small">{d.iso_56001_clauses.join(' · ')}</div></td>
                    {(['executive', 'management', 'practitioner'] as const).map((lv) => (
                      <td key={lv} className="num">
                        {d.by_level[lv]?.suppressed
                          ? <span className="muted small" title={res.note}>n&lt;{res.config.min_segment_n}</span>
                          : d.by_level[lv]?.score ?? '—'}</td>
                    ))}
                    <td className="num">{d.gap}</td>
                    <td>{d.gap_flagged && <span className="pill act-verify">≥{res.config.gap_threshold}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">{res.note}</p>
          </div>
        </>
      )}

      {sec === 'quadrant' && quad && (
        <div className="card">
          <h3>Maturity × Value</h3>
          <div className="matrix" style={{ height: 220 }}>
            <span className="matrix-corner tl" title="Value without repeatable capability">{quad.labels.tl}</span>
            <span className="matrix-corner tr" title="Capability converting into value">{quad.labels.tr}</span>
            <span className="matrix-corner bl" title="Neither capability nor value">{quad.labels.bl}</span>
            <span className="matrix-corner br" title="Capable but not converting">{quad.labels.br}</span>
            {quad.points.map((p) => (
              <span key={p.campaign} className="dot dot-quick_win"
                    style={{ left: `${p.maturity * 0.9 + 5}%`, top: `${95 - p.value * 0.88}%`, width: 14, height: 14 }}
                    title={`${p.campaign}: maturity ${p.maturity}, value ${p.value}`} />
            ))}
          </div>
          <div className="matrix-axes muted small">
            <span>← maturity composite (threshold {quad.maturity_threshold})</span>
            <span>value index (threshold {quad.value_threshold}) ↑</span>
          </div>
        </div>
      )}

      {sec === 'roadmap' && (
        <div className="card">
          <div className="card-header"><h3>Roadmap</h3>
            <span className="row">
              <button className="secondary" onClick={async () => {
                await fetch(`/api/audit/campaigns/${cid}/roadmap/generate`, { method: 'POST' })
                toast('Regenerated — accepted and dismissed items were preserved.'); load()
              }}>Regenerate</button>
              <a className="chip" href={exportUrl(`/api/audit/campaigns/${cid}/roadmap?format=csv`)} download>Export CSV</a>
            </span></div>
          {(['now', 'next', 'later'] as const).map((h) => (
            <div key={h}>
              <h4>{h === 'now' ? 'Now (0–90 days)' : h === 'next' ? 'Next (3–9 months)' : 'Later (9–18 months)'}</h4>
              {items.filter((i) => i.horizon === h).map((i) => (
                <div key={i.id} className="decision-row">
                  <span className="pill act-approve" title="priority = (80 − score) × impact ÷ effort">{i.priority}</span>
                  <span style={{ flex: 1 }}><strong>{i.title}</strong>{' '}
                    <span className="muted small">{i.description} · {i.status}
                      {i.owner ? ` · ${i.owner}` : ''}</span></span>
                  {i.status === 'generated' && (
                    <span className="row">
                      <button className="chip" onClick={async () => {
                        await fetch(`/api/audit/roadmap/${i.id}`, { method: 'PATCH',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ status: 'accepted' }) }); load()
                      }}>accept</button>
                      <button className="chip" onClick={async () => {
                        await fetch(`/api/audit/roadmap/${i.id}`, { method: 'PATCH',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ status: 'dismissed' }) }); load()
                      }}>dismiss</button>
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
