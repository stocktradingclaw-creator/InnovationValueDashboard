import { useEffect, useState } from 'react'
import { money, toast } from '../api'

interface Dim {
  key: string; name: string; target: number; weight: string
  respondents: number; self_avg: number | null; calibrated: number | null
  optimism_flag: boolean; gap_weighted: number | null
  benchmarks: Record<string, number | null>
  root_causes: string[]; value_type: string | null
  value_low: number | null; value_high: number | null
  value_confidence: string | null; effort: string | null; evidence: string[]
}
interface Summary { wave_id: number; dimensions: Dim[]; overall_calibrated: number | null
  total_value_low: number; total_value_high: number }
interface Readout { waves: { id: number; name: string }[]; latest?: Summary
  trend?: { wave: string; dimensions: Record<string, number | null> }[]
  top_gaps?: Dim[]; roadmap?: Record<string, { id: number; title: string; owner: string | null; status: string; uplift: number; dimensions: string[] }[]> }

function Radar({ dims, series }: { dims: Dim[]; series: Record<string, boolean> }) {
  const N = dims.length, R = 90, CX = 130, CY = 110
  const pt = (i: number, v: number) => {
    const a = (Math.PI * 2 * i) / N - Math.PI / 2
    return `${CX + Math.cos(a) * (v / 5) * R},${CY + Math.sin(a) * (v / 5) * R}`
  }
  const poly = (get: (d: Dim) => number | null) =>
    dims.map((d, i) => pt(i, get(d) ?? 0)).join(' ')
  const benchNames = Object.keys(dims[0]?.benchmarks ?? {})
  return (
    <svg viewBox="0 0 340 230" role="img" aria-label="Maturity radar: calibrated vs target vs benchmarks">
      {[1, 2, 3, 4, 5].map((r) => (
        <polygon key={r} points={dims.map((_, i) => pt(i, r)).join(' ')}
                 fill="none" stroke="var(--border)" strokeWidth="0.6" />
      ))}
      {dims.map((d, i) => {
        const [x, y] = pt(i, 5.45).split(',').map(Number)
        return <text key={d.key} x={x} y={y} textAnchor="middle"
                     style={{ fill: 'var(--muted)', fontSize: 7 }}>{d.name.split(' ')[0]}</text>
      })}
      {series.target && <polygon points={poly((d) => d.target)} fill="none"
        stroke="var(--info)" strokeWidth="1.5" strokeDasharray="4 3" />}
      {benchNames.map((b, bi) => series[b] && (
        <polygon key={b} points={poly((d) => d.benchmarks[b])} fill="none"
                 stroke={bi ? 'var(--purple)' : 'var(--warn)'} strokeWidth="1" strokeDasharray="2 3" />
      ))}
      {series.calibrated && <polygon points={poly((d) => d.calibrated)}
        fill="rgba(76,195,138,0.15)" stroke="var(--accent)" strokeWidth="2" />}
    </svg>
  )
}

export default function Maturity() {
  const [r, setR] = useState<Readout | null>(null)
  const [waveId, setWaveId] = useState<number | null>(null)
  const [sum, setSum] = useState<Summary | null>(null)
  const [series, setSeries] = useState<Record<string, boolean>>({ calibrated: true, target: true })
  const [editFw, setEditFw] = useState(false)
  const [fw, setFw] = useState<{ name: string; dimensions: { key: string; name: string; target: number; weight: string; rubric: Record<string, string> }[] } | null>(null)
  const [csv, setCsv] = useState('')
  const load = () => fetch('/api/maturity/readout').then((x) => x.json()).then((d) => {
    setR(d)
    if (d.waves?.length) {
      const id = waveId ?? d.waves[d.waves.length - 1].id
      setWaveId(id)
      fetch(`/api/maturity/waves/${id}/summary`).then((x) => x.json()).then(setSum)
    }
  }).catch(() => {})
  useEffect(() => { load() }, [waveId])
  useEffect(() => { fetch('/api/maturity/framework').then((x) => x.json()).then(setFw) }, [])

  if (!r) return <section aria-busy="true"><div className="card skeleton sk-block" style={{ height: 120 }} /></section>
  if (!r.waves.length) {
    return (
      <section>
        <h2>Maturity assessment</h2>
        <p className="muted">No assessment waves yet — seed the demo in Hub Settings, or create
          your baseline wave:</p>
        <button onClick={async () => {
          await fetch('/api/maturity/waves', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: 'Baseline' }) })
          load()
        }}>Create baseline wave</button>
      </section>
    )
  }
  const latest = sum ?? r.latest!
  const dims = latest.dimensions
  const benchNames = Object.keys(dims[0]?.benchmarks ?? {})
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Maturity assessment</h2>
          <p className="muted">Frame → diagnose → benchmark → size the gaps → plan → re-measure.</p>
        </div>
        <div className="row">
          <select value={waveId ?? ''} onChange={(e) => setWaveId(Number(e.target.value))} aria-label="Assessment wave">
            {r.waves.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <button className="secondary" onClick={async () => {
            const name = window.prompt('Name the new wave (e.g. Wave 3 — Q1)')
            if (!name) return
            await fetch('/api/maturity/waves', { method: 'POST',
              headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) })
            load(); toast(`Wave "${name}" created — capture responses below.`)
          }}>+ New wave</button>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Executive readout</h3>
          <button className="secondary" onClick={() => window.print()}>Print / PDF</button>
        </div>
        <div className="metrics-row">
          <div className="metric"><span className="muted small">Overall maturity (calibrated)</span>
            <strong>{latest.overall_calibrated ?? '—'} / 5</strong></div>
          <div className="metric"><span className="muted small">Value at stake (range)</span>
            <strong>{money(latest.total_value_low)} – {money(latest.total_value_high)}</strong></div>
          <div className="metric"><span className="muted small">Top gap by value</span>
            <strong>{r.top_gaps?.[0]?.name ?? '—'}</strong></div>
        </div>
        {(r.top_gaps ?? []).map((g) => (
          <div key={g.key} className="decision-row">
            <span className="pill act-verify">gap</span>
            <span><strong>{g.name}</strong>{' '}
              <span className="muted small">{g.calibrated} → target {g.target} ·{' '}
                {g.value_type} · {money(g.value_low ?? 0)}–{money(g.value_high ?? 0)} ·
                causes: {g.root_causes.join(', ') || '—'}</span></span>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Benchmark radar</h3>
          <div className="row">
            {['calibrated', 'target', ...benchNames].map((k) => (
              <button key={k} className={series[k] ? 'chip chip-active' : 'chip'}
                      onClick={() => setSeries({ ...series, [k]: !series[k] })}>{k.split(' (')[0]}</button>
            ))}
          </div>
        </div>
        <Radar dims={dims} series={series} />
        <p className="muted small">Benchmark series are editable placeholder data — replace with
          your industry figures via the API or keep as directional reference.</p>
      </div>

      <div className="card">
        <h3>Heat map — gap to target across waves</h3>
        <table className="kpi-table">
          <thead><tr><th>Dimension</th>{r.trend?.map((t) => <th key={t.wave}>{t.wave}</th>)}<th>Target</th></tr></thead>
          <tbody>
            {dims.map((d) => (
              <tr key={d.key}>
                <td><strong>{d.name}</strong>{d.optimism_flag &&
                  <span className="pill act-verify" title="Self-score exceeds calibrated by ≥1 — self-ratings skew optimistic"> self +1↑</span>}</td>
                {r.trend?.map((t) => {
                  const v = t.dimensions[d.key]
                  const gap = v != null ? d.target - v : null
                  return <td key={t.wave} className="num" style={{
                    background: gap == null ? undefined :
                      gap <= 0 ? 'rgba(76,195,138,0.18)' : gap <= 1 ? 'rgba(255,171,112,0.15)' : 'rgba(229,83,75,0.15)' }}>
                    {v ?? '—'}</td>
                })}
                <td className="num muted">{d.target}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Gaps &amp; value at stake — wave detail</h3>
        <table className="kpi-table">
          <thead><tr><th>Dimension</th><th className="num">Self avg</th><th className="num">Calibrated</th>
            <th className="num">Weighted gap</th><th>Value at stake</th><th>Effort</th></tr></thead>
          <tbody>
            {dims.map((d) => (
              <tr key={d.key}>
                <td><strong>{d.name}</strong><div className="muted small">{d.weight} · n={d.respondents}</div></td>
                <td className="num">{d.self_avg ?? '—'}{d.optimism_flag ? ' ⚠' : ''}</td>
                <td className="num"><input type="number" min={1} max={5} step={0.5} defaultValue={d.calibrated ?? ''}
                  style={{ width: 64 }} aria-label={`Calibrated score for ${d.name}`}
                  onBlur={async (e) => {
                    const v = Number(e.target.value)
                    if (!v || v === d.calibrated) return
                    await fetch(`/api/maturity/waves/${latest.wave_id}/calibration`, {
                      method: 'PUT', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ dimension: d.key, score: v }) })
                    toast(`${d.name} calibrated to ${v}.`); load()
                  }} /></td>
                <td className="num">{d.gap_weighted ?? '—'}</td>
                <td className="small">{d.value_type
                  ? `${d.value_type}: ${money(d.value_low ?? 0)}–${money(d.value_high ?? 0)} (${d.value_confidence})`
                  : <span className="muted">not sized</span>}</td>
                <td>{d.effort ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Prioritization — value at stake vs effort</h3>
        <div className="matrix" style={{ height: 200 }}>
          <span className="matrix-corner tl">Quick wins</span>
          <span className="matrix-corner tr">Big bets</span>
          <span className="matrix-corner bl">Incremental</span>
          <span className="matrix-corner br">Deprioritize</span>
          {dims.filter((d) => d.value_high).map((d) => {
            const eff = d.effort === 'high' ? 0.8 : d.effort === 'medium' ? 0.5 : 0.2
            const maxV = Math.max(...dims.map((x) => x.value_high ?? 0), 1)
            return <span key={d.key} className="dot dot-quick_win"
              style={{ left: `${eff * 90 + 5}%`, top: `${95 - ((d.value_high ?? 0) / maxV) * 88}%`, width: 14, height: 14 }}
              title={`${d.name}: ${money(d.value_low ?? 0)}–${money(d.value_high ?? 0)}, effort ${d.effort}`} />
          })}
        </div>
        <div className="matrix-axes muted small"><span>← lower effort</span><span>higher effort →</span></div>
      </div>

      <div className="card">
        <h3>Roadmap</h3>
        <div className="fmap">
          {Object.entries(r.roadmap ?? {}).map(([h, inits]) => (
            <div key={h} className="fmap-col">
              <div className="lc-phase-head lc-tone-idea"><strong>{h}</strong>
                <span className="muted small">{inits.length}</span></div>
              {inits.map((i) => (
                <div key={i.id} className="fmap-node">
                  <span className="small"><strong>{i.title}</strong><br />
                    <span className="muted">{i.owner ?? 'unowned'} · +{i.uplift} level(s) on{' '}
                      {i.dimensions.join(', ')} · {i.status}</span></span>
                </div>
              ))}
            </div>
          ))}
        </div>
        <button className="chip" onClick={async () => {
          const title = window.prompt('Initiative title')
          if (!title) return
          await fetch('/api/maturity/initiatives', { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, horizon: '0-3m' }) })
          toast('Initiative added to the 0-3m horizon.'); load()
        }}>+ Add initiative</button>
      </div>

      <div className="card">
        <h3>Capture responses — {r.waves.find((w) => w.id === waveId)?.name}</h3>
        <p className="muted small">Paste survey CSV (respondent,dimension,score,evidence). Dimension
          keys: {fw?.dimensions.map((d) => d.key).join(', ')}</p>
        <textarea rows={3} value={csv} onChange={(e) => setCsv(e.target.value)}
                  placeholder={'respondent,dimension,score,evidence\nmaria,velocity,3,shipped 4 experiments'} />
        <div className="row">
          <button disabled={!csv.trim()} onClick={async () => {
            const res = await fetch(`/api/maturity/waves/${waveId}/responses`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ csv }) })
            const d = await res.json()
            if (!res.ok) { toast(d.detail ?? 'import failed'); return }
            setCsv(''); toast(`${d.added} response(s) imported.`); load()
          }}>Import responses</button>
          <button className="secondary" onClick={() => setEditFw(!editFw)}>
            {editFw ? 'Hide framework editor' : 'Edit framework'}</button>
        </div>
        {editFw && fw && (
          <div className="plan">
            {fw.dimensions.map((d, i) => (
              <div key={d.key} className="row objective-row">
                <input value={d.name} aria-label="Dimension name" onChange={(e) => {
                  const dd = [...fw.dimensions]; dd[i] = { ...d, name: e.target.value }
                  setFw({ ...fw, dimensions: dd }) }} />
                <select value={d.target} aria-label="Target level" onChange={(e) => {
                  const dd = [...fw.dimensions]; dd[i] = { ...d, target: Number(e.target.value) }
                  setFw({ ...fw, dimensions: dd }) }}>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>target {n}</option>)}
                </select>
                <select value={d.weight} aria-label="Strategic weight" onChange={(e) => {
                  const dd = [...fw.dimensions]; dd[i] = { ...d, weight: e.target.value }
                  setFw({ ...fw, dimensions: dd }) }}>
                  {['critical', 'important', 'supporting'].map((w) => <option key={w}>{w}</option>)}
                </select>
              </div>
            ))}
            <button onClick={async () => {
              const res = await fetch('/api/maturity/framework', { method: 'PUT',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(fw) })
              toast(res.ok ? 'Framework saved.' : 'Save failed.'); load()
            }}>Save framework</button>
          </div>
        )}
      </div>
    </section>
  )
}
