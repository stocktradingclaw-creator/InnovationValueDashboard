import { useEffect, useState } from 'react'
import type { UserProfile } from '../api'
import { ContextPicker } from './Dashboard'
import {
   createInitiative, demoGenerate, demoRevert, 
  getDemoStatus, getInitiatives, getScoringConfig, getWorkflow, putGovernance,
  putScoringConfig, putWorkflow, reorderInitiatives,  updateInitiative,
  getUsers,
  putUsers,
  seedLifecycle,
  getNotificationSettings,
  putNotificationSettings,
  
} from '../api'
import { getGovernance } from '../api'
import type { DemoStatus, Initiative, ScoringConfig, WorkflowStep } from '../types'

const AREA_LABELS: Record<string, string> = {
  idea_screening: 'Idea screening',
  business_case_approval: 'Business case approval',
  delivery: 'Delivery',
  value_verification: 'Value verification',
  portfolio_oversight: 'Portfolio oversight',
}

function WorkflowEditor() {
  const [steps, setSteps] = useState<WorkflowStep[]>([])
  const [forums, setForums] = useState<string[]>([])
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getWorkflow().then((r) => { setSteps(r.steps); setForums(r.forums) })
  }, [])

  const edit = (i: number, patch: Partial<WorkflowStep>) =>
    setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)))

  return (
    <div className="card">
      <h3>Innovation workflow</h3>
      <p className="muted small">
        The gates every idea walks through, in order. Edit any gate, or add steps between intake
        and business-case development — the queues, lifecycle strip, and pipeline follow this
        definition immediately.
      </p>
      <div className="wf-editor">
        {steps.map((s, i) => (
          <div key={i} className="wf-step card">
            <div className="row">
              <span className="lifecycle-box"><strong>{i + 1}</strong><span>gate</span></span>
              <input value={s.label} aria-label="Step label"
                     onChange={(e) => edit(i, { label: e.target.value })} />
              <input value={s.gate} aria-label="Gate name"
                     onChange={(e) => edit(i, { gate: e.target.value })} />
              <select value={s.forum} onChange={(e) => edit(i, { forum: e.target.value })}>
                {forums.map((f) => <option key={f} value={f}>{AREA_LABELS[f] ?? f}</option>)}
              </select>
              {i > 0 && (
                <button className="danger" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                  Remove
                </button>
              )}
            </div>
            <input
              value={s.purpose} placeholder="Purpose — what this gate decides"
              onChange={(e) => edit(i, { purpose: e.target.value })}
            />
            <input
              value={s.criteria.join(', ')} placeholder="Gate criteria, comma-separated"
              onChange={(e) => edit(i, { criteria: e.target.value.split(',').map((c) => c.trim()).filter(Boolean) })}
            />
            {i < steps.length - 1 && <div className="wf-connector">↓</div>}
          </div>
        ))}
      </div>
      <div className="row">
        <button
          className="secondary"
          onClick={() => {
            const n = steps.length
            setSteps([...steps, {
              key: `step_${Date.now() % 100000}`, label: `New step ${n}`, gate: 'New gate',
              forum: 'idea_screening', purpose: '', criteria: [],
            }])
          }}
        >
          + Add step
        </button>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true); setMsg(null)
            try {
              const r = await putWorkflow(steps)
              setSteps(r.steps)
              setMsg('Workflow saved — gates apply immediately.')
            } catch (e) {
              setMsg(e instanceof Error ? e.message : String(e))
            } finally { setBusy(false) }
          }}
        >
          {busy ? 'Saving…' : 'Save workflow'}
        </button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
      <p className="muted small">
        Intake (step 1) is fixed as the entry point; business-case development always follows the
        final gate.
      </p>
    </div>
  )
}

function ScoringSettings() {
  const [config, setConfig] = useState<ScoringConfig | null>(null)
  const [themes, setThemes] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    getScoringConfig().then((c) => { setConfig(c); setThemes(c.priority_themes.join(', ')) })
  }, [])
  if (!config) return null
  const total = Object.values(config.idea_weights).reduce((a, b) => a + b, 0)
    + config.custom_criteria.reduce((a, c) => a + c.weight, 0) || 1

  return (
    <div className="card">
      <h3>Scoring framework</h3>
      <p className="muted small">
        Tune the built-in weights, declare priority themes and guardrails, and add your own
        criteria — custom criteria match idea text against keywords and carry their own weight.
      </p>
      <h4>Idea triage weights</h4>
      {Object.entries(config.idea_weights).map(([key, value]) => (
        <div key={key} className="weight-row">
          <span className="weight-label">{key.replace('_', ' ')}</span>
          <input type="range" min={0} max={100} value={Math.round(value * 100)}
                 onChange={(e) => setConfig({ ...config, idea_weights: { ...config.idea_weights, [key]: Number(e.target.value) / 100 } })} />
          <span className="weight-pct">{Math.round((value / total) * 100)}%</span>
        </div>
      ))}
      <h4>Opportunity ranking weights</h4>
      <p className="muted small">Drive the ranking on the Opportunities tab for everyone.</p>
{Object.entries(config.opportunity_weights).map(([key, value]) => (
        <div key={key} className="weight-row">
          <span className="weight-label">{key.replace('_', ' ')}</span>
          <input type="range" min={0} max={100} value={Math.round(value * 100)}
                 onChange={(e) => setConfig({ ...config, opportunity_weights: { ...config.opportunity_weights, [key]: Number(e.target.value) / 100 } })} />
          <span className="weight-pct">{Math.round((value / total) * 100)}%</span>
        </div>
      ))}
      <h4>Custom criteria</h4>
      {config.custom_criteria.map((c, i) => (
        <div key={i} className="row">
          <input value={c.label} placeholder="Criterion label"
                 onChange={(e) => setConfig({ ...config, custom_criteria: config.custom_criteria.map((x, j) => j === i ? { ...x, label: e.target.value } : x) })} />
          <input value={c.keywords.join(', ')} placeholder="Keywords, comma-separated"
                 onChange={(e) => setConfig({ ...config, custom_criteria: config.custom_criteria.map((x, j) => j === i ? { ...x, keywords: e.target.value.split(',').map((k) => k.trim()).filter(Boolean) } : x) })} />
          <input type="number" step="0.05" min="0" value={c.weight} style={{ maxWidth: 90 }} aria-label="Weight"
                 onChange={(e) => setConfig({ ...config, custom_criteria: config.custom_criteria.map((x, j) => j === i ? { ...x, weight: Number(e.target.value) } : x) })} />
          <button className="danger" onClick={() => setConfig({ ...config, custom_criteria: config.custom_criteria.filter((_, j) => j !== i) })}>Remove</button>
        </div>
      ))}
      <div className="row">
        <button className="secondary"
                onClick={() => setConfig({ ...config, custom_criteria: [...config.custom_criteria, { label: '', keywords: [], weight: 0.2 }] })}>
          + Add criterion
        </button>
      </div>
      <input placeholder="Strategic priority themes, comma-separated" value={themes}
             onChange={(e) => setThemes(e.target.value)} />
      <div className="row guardrail-row">
        <label className="small">
          Min annual benefit $
          <input type="number" value={config.guardrails.min_annual_benefit || ''}
                 onChange={(e) => setConfig({ ...config, guardrails: { ...config.guardrails, min_annual_benefit: Number(e.target.value) || 0 } })} />
        </label>
        <label className="small">
          <input type="checkbox" checked={config.guardrails.require_category} style={{ width: 'auto' }}
                 onChange={(e) => setConfig({ ...config, guardrails: { ...config.guardrails, require_category: e.target.checked } })} /> require category
        </label>
        <label className="small">
          <input type="checkbox" checked={config.guardrails.require_benefit_estimate} style={{ width: 'auto' }}
                 onChange={(e) => setConfig({ ...config, guardrails: { ...config.guardrails, require_benefit_estimate: e.target.checked } })} /> require benefit estimate
        </label>
      </div>
      <div className="row">
        <button disabled={busy} onClick={async () => {
          setBusy(true); setMsg(null)
          try {
            await putScoringConfig({ ...config, priority_themes: themes.split(',').map((t) => t.trim()).filter(Boolean) })
            setMsg('Saved — applies to all new triage.')
          } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
        }}>{busy ? 'Saving…' : 'Save framework'}</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function UserProfiles() {
  const [users, setUsers] = useState<UserProfile[]>([])
  const [roles, setRoles] = useState<string[]>([])
  const [caps, setCaps] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => {
    getUsers().then((r) => { setUsers(r.users); setRoles(r.roles); setCaps(r.capabilities) })
  }, [])
  const edit = (i: number, patch: Partial<UserProfile>) =>
    setUsers(users.map((u, j) => (j === i ? { ...u, ...patch } : u)))
  return (
    <div className="card">
      <h3>User profiles &amp; access levels</h3>
      <p className="muted small">
        The hub is open until profiles exist. Once any are added, signing in is required,
        every decision is checked against the signed-in user's access level, and Hub
        Settings itself becomes admin-only. Users without a password cannot sign in
        until one is set here.
      </p>
      <ul className="muted small">
        {Object.entries(caps).map(([r, c]) => (
          <li key={r}><strong>{r}</strong> — {c}</li>
        ))}
      </ul>
      {users.map((u, i) => (
        <div key={i} className="row objective-row">
          <input placeholder="Name" value={u.name} onChange={(e) => edit(i, { name: e.target.value })} />
          <select value={u.role} onChange={(e) => edit(i, { role: e.target.value })}>
            {roles.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <input type="password" autoComplete="new-password"
                 placeholder={u.has_password ? 'password set — type to replace' : 'set password'}
                 value={u.password ?? ''}
                 onChange={(e) => edit(i, { password: e.target.value })} />
          <button className="secondary" onClick={() => setUsers(users.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div className="row">
        <button className="secondary"
                onClick={() => setUsers([...users, { name: '', role: roles[1] ?? 'reviewer' }])}>
          + Add user
        </button>
        <button disabled={busy} onClick={async () => {
          setBusy(true); setMsg(null)
          try {
            const r = await putUsers(users.filter((u) => u.name.trim()))
            setUsers(r.users)
            setMsg('Saved.')
          } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
        }}>{busy ? 'Saving\u2026' : 'Save profiles'}</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function AiSettings() {
  const [masked, setMasked] = useState('')
  const [source, setSource] = useState('none')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = () => fetch('/api/settings/ai').then((r) => r.json())
    .then((d) => { setMasked(d.masked); setSource(d.source) }).catch(() => {})
  useEffect(() => { load() }, [])
  return (
    <div className="card">
      <h3>AI engine key</h3>
      <p className="muted small">
        Powers every AI call on the platform — drafting, triage, red team, research, studios.
        {source === 'environment' && ' Currently using the deployment environment key.'}
        {source === 'workspace' && ' Currently using the workspace key set here.'}
        {source === 'none' && ' No key configured — AI features run in labeled template mode.'}
      </p>
      <div className="row">
        <input type="password" autoComplete="off"
               placeholder={masked ? `configured: ${masked} — paste to replace` : 'sk-ant-…'}
               value={key} onChange={(e) => setKey(e.target.value)} />
        <button disabled={busy || !key.trim()} onClick={async () => {
          setBusy(true); setMsg(null)
          try {
            const r = await fetch('/api/settings/ai', { method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ api_key: key.trim() }) })
            const d = await r.json()
            if (!r.ok) throw new Error(d.detail ?? 'save failed')
            setKey(''); setMsg('Saved — all AI calls now use this key.'); load()
          } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
          finally { setBusy(false) }
        }}>{busy ? 'Saving…' : 'Save key'}</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function NotificationSettings() {
  const [webhook, setWebhook] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => { getNotificationSettings().then((r) => setWebhook(r.webhook)).catch(() => {}) }, [])
  return (
    <div className="card">
      <h3>Notifications beyond the hub</h3>
      <p className="muted small">
        Post every submitter notification to a Teams or Slack incoming webhook so people
        hear about decisions where they already work. Leave empty to keep notifications
        in-app only.
      </p>
      <div className="row">
        <input placeholder="https://outlook.office.com/webhook/… or https://hooks.slack.com/…"
               value={webhook} onChange={(e) => setWebhook(e.target.value)} />
        <button disabled={busy} onClick={async () => {
          setBusy(true); setMsg(null)
          try { await putNotificationSettings(webhook.trim()); setMsg('Saved.') }
          catch (e) { setMsg(e instanceof Error ? e.message : String(e)) }
          finally { setBusy(false) }
        }}>{busy ? 'Saving…' : 'Save'}</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function RolesAccess() {
  const [assignments, setAssignments] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => {
    getGovernance().then((r) =>
      setAssignments(Object.fromEntries(Object.entries(r.assignments).map(([k, v]) => [k, v.join(', ')]))))
  }, [])
  return (
    <div className="card">
      <h3>Roles &amp; access</h3>
      <p className="muted small">
        Assign people to each workflow area. Areas with owners only accept decisions from those
        people; empty areas are open until configured.
      </p>
      {Object.keys(AREA_LABELS).map((area) => (
        <div key={area} className="gov-row">
          <span className="funnel-label">{AREA_LABELS[area]}</span>
          <input placeholder="names, comma-separated" value={assignments[area] ?? ''}
                 onChange={(e) => setAssignments({ ...assignments, [area]: e.target.value })} />
        </div>
      ))}
      <div className="row">
        <button disabled={busy} onClick={async () => {
          setBusy(true); setMsg(null)
          try {
            await putGovernance(Object.fromEntries(Object.entries(assignments).map(([k, v]) => [k, v.split(',').map((s) => s.trim()).filter(Boolean)])))
            setMsg('Saved.')
          } catch (e) { setMsg(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
        }}>{busy ? 'Saving…' : 'Save roles'}</button>
        {msg && <span className="muted small">{msg}</span>}
      </div>
    </div>
  )
}

function Objectives() {
  const [items, setItems] = useState<Initiative[]>([])
  const [name, setName] = useState('')
  const [objective, setObjective] = useState('')
  const load = () => getInitiatives().then((r) => setItems(r.initiatives))
  useEffect(() => { load() }, [])
  const move = async (i: number, dir: -1 | 1) => {
    const order = [...items]
    const j = i + dir
    if (j < 0 || j >= order.length) return
    ;[order[i], order[j]] = [order[j], order[i]]
    setItems(order)
    await reorderInitiatives(order.map((x) => x.id))
  }
  return (
    <div className="card">
      <h3>Strategic objectives</h3>
      <p className="muted small">
        Ordered by priority — ideas tagged to an objective score as aligned, and value rolls up
        per objective on the Overview.
      </p>
      {items.map((it, i) => (
        <div key={it.id} className="row objective-row">
          <span className="muted small">#{i + 1}</span>
          <input defaultValue={it.name} aria-label="Objective name"
                 onBlur={(e) => e.target.value !== it.name && updateInitiative(it.id, { name: e.target.value }).then(load)} />
          <input defaultValue={it.objective} aria-label="Objective statement"
                 onBlur={(e) => e.target.value !== it.objective && updateInitiative(it.id, { objective: e.target.value }).then(load)} />
          <button className="secondary" aria-label="Move up" onClick={() => move(i, -1)}>↑</button>
          <button className="secondary" aria-label="Move down" onClick={() => move(i, 1)}>↓</button>
        </div>
      ))}
      <div className="row">
        <input placeholder="New objective name" value={name} onChange={(e) => setName(e.target.value)} />
        <input placeholder="What outcome must it deliver?" value={objective} onChange={(e) => setObjective(e.target.value)} />
        <button disabled={!name.trim() || !objective.trim()} onClick={async () => {
          await createInitiative({ name, objective }); setName(''); setObjective(''); load()
        }}>Create</button>
      </div>
    </div>
  )
}

function DemoStudio({ onDone }: { onDone: () => void }) {
  const [seeding, setSeeding] = useState(false)
  const [seedMsg, setSeedMsg] = useState<string | null>(null)
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [industries, setIndustries] = useState<string[]>([])
  const [clientName, setClientName] = useState('')
  const [industry, setIndustry] = useState('')
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = () => getDemoStatus().then((r) => { setStatus(r.demo); setIndustries(r.industries) }).catch(() => {})
  useEffect(() => { load() }, [])
  return (
    <div className="card demo-studio">
      <h3>Demo studio</h3>
      <p className="muted small">
        Name the client and the AI researches their publicly stated strategy to ground ten ideas
        in it (industry optional); industry-only follows its latest trends. Revert restores the
        exact pre-demo baseline.
      </p>
      <div className="row" style={{ marginBottom: '0.8rem' }}>
        <button className="secondary" disabled={seeding} onClick={async () => {
          setSeeding(true)
          try {
            const r = await seedLifecycle()
            setSeedMsg(`Seeded ${r.ideas} ideas and ${r.cases} business cases across every phase.`)
          } catch (e) { setSeedMsg(e instanceof Error ? e.message : String(e)) }
          finally { setSeeding(false) }
        }}>{seeding ? 'Seeding…' : 'Seed full-lifecycle sample data'}</button>
        <button className="secondary" onClick={async () => {
          const res = await fetch('/api/demo/clear', { method: 'POST' })
          const d = await res.json()
          setSeedMsg(res.ok ? d.note : 'Clear failed.')
        }}>Clear company/industry data</button>
        <button className="secondary" onClick={async () => {
          if (!window.confirm('Clear ALL demo data? The hub will be empty until re-seeded.')) return
          const res = await fetch('/api/demo/clear?all=true', { method: 'POST' })
          setSeedMsg(res.ok ? 'Everything cleared — the hub is empty.' : 'Clear failed.')
        }}>Clear everything</button>
        {seedMsg && <span className="muted small">{seedMsg}</span>}
      </div>
      {status ? (
        <>
          <div className="banner-ok">
            Active demo: <strong>{status.client}</strong> ({status.industry}) — {status.initiatives}{' '}
            initiatives, {status.ideas} ideas, by {status.generated_by}.
          </div>
          <button className="danger" disabled={busy === 'revert'} onClick={async () => {
            setBusy('revert'); setError(null)
            try { await demoRevert(); await load(); onDone() }
            catch (e) { setError(e instanceof Error ? e.message : String(e)) }
            finally { setBusy(null) }
          }}>{busy === 'revert' ? 'Reverting…' : 'Revert to baseline'}</button>
        </>
      ) : (
        <>
          <div className="row">
            <input placeholder="Client name — the AI researches their public strategy"
                   value={clientName} onChange={(e) => setClientName(e.target.value)} />
            <select value={industry} onChange={(e) => setIndustry(e.target.value)}>
              <option value="">Industry (optional with a client name)…</option>
              {industries.map((i) => <option key={i} value={i}>{i}</option>)}
            </select>
          </div>
          <input placeholder="Presentation focus (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <div className="row">
            <button disabled={busy === 'generate' || (!clientName.trim() && !industry)} onClick={async () => {
              setBusy('generate'); setError(null)
              try {
                await demoGenerate({ client: clientName.trim() || undefined, industry: industry || undefined, notes: notes || undefined })
                setClientName(''); setIndustry(''); setNotes(''); await load(); onDone()
              } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(null) }
            }}>{busy === 'generate' ? 'Researching & generating (1–3 min)…' : 'Generate client portfolio'}</button>
            <span className="muted small">Snapshots the baseline first — fully reversible.</span>
          </div>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

const CASE_GATES: [string, string][] = [
  ['AI business case', 'Hub drafts the ROI plan with frozen metric baselines'],
  ['Executive review', 'Value, opportunity cost, and ROI on the table'],
  ['Funding gate', 'A released tranche is required to mobilize'],
]

const VALUE_GATES: [string, string][] = [
  ['Delivery', 'Build and implement'],
  ['Live', 'Go-live starts the measurement clock'],
  ['Value verified', 'Re-observed against the frozen baseline'],
  ['Scale', 'Proven patterns replicated across the estate'],
]

function LifecycleMap() {
  const [steps, setSteps] = useState<WorkflowStep[]>([])
  useEffect(() => { getWorkflow().then((r) => setSteps(r.steps)).catch(() => {}) }, [])
  // one continuous numbering across the whole lifecycle
  const n = steps.length
  const numbered = (gates: [string, string][], start: number): [string, string][] =>
    gates.map(([label, hint], i) => [`${start + i}. ${label}`, hint])
  const phases: { name: string; hint: string; tone: string; gates: [string, string][] }[] = [
    {
      name: 'Ideation',
      hint: 'configurable below',
      tone: 'lc-tone-idea',
      gates: steps.map((st, i) => [`${i + 1}. ${st.label}`, st.gate] as [string, string]),
    },
    { name: 'Business case & funding', hint: 'fixed', tone: 'lc-tone-case',
      gates: numbered(CASE_GATES, n + 1) },
    { name: 'Delivery & value', hint: 'fixed', tone: 'lc-tone-value',
      gates: numbered(VALUE_GATES, n + 1 + CASE_GATES.length) },
  ]
  return (
    <div className="card">
      <h3>The end-to-end innovation lifecycle</h3>
      <p className="muted small">
        Every idea travels this path. The ideation gates are yours to shape in the workflow
        editor below; the business-case, funding, and value phases are fixed so verified ROI
        always means the same thing.
      </p>
      <div className="lc-map">
        {phases.map((ph, pi) => (
          <div key={ph.name} className="lc-phase-wrap">
            {pi > 0 && <span className="lc-arrow" aria-hidden="true">➜</span>}
            <div className="lc-phase">
              <div className={`lc-phase-head ${ph.tone}`}>
                <strong>{ph.name}</strong>
                <span className="muted small">{ph.hint}</span>
              </div>
              <div className="lc-nodes">
                {ph.gates.map(([label, hint]) => (
                  <span key={label} className="lc-node" title={hint}>
                    <strong>{label}</strong>
                    <span className="muted small">{hint}</span>
                  </span>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function Settings({ onChanged }: { onChanged: () => void }) {
  return (
    <section>
      <h2>Hub settings</h2>
      <p className="muted">
        Configure how the hub runs: the workflow itself, who decides what, what "good" scores as,
        the strategy it aligns to, and the demo studio.
      </p>
      <LifecycleMap />
      <WorkflowEditor />
      <div className="dash-grid">
        <ScoringSettings />
        <ContextPicker />
      <AiSettings />
      <UserProfiles />
      <NotificationSettings />
      <RolesAccess />
      </div>
      <div className="dash-grid">
        <Objectives />
      </div>
      <DemoStudio onDone={onChanged} />
    </section>
  )
}
