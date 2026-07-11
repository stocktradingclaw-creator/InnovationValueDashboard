import { useCallback, useEffect, useState } from 'react'
import {
  advanceMvpStage, generateMvpStage, getMvpOverview, getMvpPlan, toast,
} from '../api'
import type { MvpOverviewRow, MvpPlan, MvpStageState } from '../api'

const money = (v: number | null | undefined) =>
  v == null ? '—' : `$${Math.round(v).toLocaleString()}`

function StagePanel({ plan, stage, onChanged }: {
  plan: MvpPlan; stage: string; onChanged: () => void
}) {
  const st: MvpStageState = plan.stages[stage] ?? {
    status: 'pending', artifact: null, note: null, completed_at: null, completed_by: null }
  const meta = plan.stage_meta[stage]
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const isCurrent = plan.current_stage === stage && st.status !== 'complete'
  const art = st.artifact

  const generate = async () => {
    setBusy(true)
    try {
      const r = await generateMvpStage(plan.case_id, stage)
      toast(`${meta.label} pack drafted (${r.artifact.generated_by === 'claude'
        ? 'AI, grounded in this case' : 'template — set an AI key in Hub Settings for a case-specific draft'})`)
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setBusy(false)
    }
  }

  const complete = async () => {
    setBusy(true)
    try {
      const r = await advanceMvpStage(plan.case_id, stage, note || undefined)
      toast(r.done
        ? 'MVP workflow complete — validated against the business case'
        : `${meta.label} complete — next: ${plan.stage_meta[r.plan.current_stage]?.label}`)
      if (r.advice) toast(r.advice)
      onChanged()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not complete stage')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>{meta.label}
          {' '}
          {st.status === 'complete' && <span className="badge badge-ok">complete</span>}
          {st.status === 'in_progress' && <span className="badge">in progress</span>}
          {isCurrent && st.status === 'pending' && <span className="pill act-verify">up next</span>}
        </h3>
        {art && (
          <span className={art.generated_by === 'claude' ? 'badge badge-ok' : 'badge'}>
            {art.generated_by === 'claude' ? 'AI draft' : 'template draft'}
          </span>
        )}
      </div>
      <p className="muted small">{meta.goal} · <em>{meta.ai_role}</em></p>

      {!art && (
        <button className="secondary" disabled={busy} onClick={generate}>
          {busy ? 'Drafting…' : `⚡ Draft the ${meta.label.toLowerCase()} pack with AI`}
        </button>
      )}

      {art && (
        <>
          <p><strong>{art.summary}</strong></p>
          {art.sections.map((s) => (
            <p key={s.title} className="small"><strong>{s.title}.</strong> {s.detail}</p>
          ))}
          <p className="small"><strong>Done when:</strong></p>
          <ul className="small">
            {art.checklist.map((c) => <li key={c}>{c}</li>)}
          </ul>
          <p className="small pending-action"><strong>Use AI here:</strong>{' '}
            {art.ai_leverage.join(' · ')}</p>
          <div className="row" style={{ gap: '0.4rem', alignItems: 'center' }}>
            <button className="secondary" disabled={busy} onClick={generate}>
              {busy ? 'Working…' : 'Re-draft'}
            </button>
            {isCurrent && (
              <>
                <input placeholder={`Sign-off note (optional)`} value={note}
                       onChange={(e) => setNote(e.target.value)} style={{ flex: 1 }} />
                <button disabled={busy} onClick={complete}>
                  Mark {meta.label.toLowerCase()} complete
                </button>
              </>
            )}
          </div>
        </>
      )}
      {st.status === 'complete' && (
        <p className="muted small">
          Completed {st.completed_at ? new Date(st.completed_at).toLocaleDateString() : ''}
          {st.completed_by ? ` by ${st.completed_by}` : ''}{st.note ? ` — ${st.note}` : ''}
        </p>
      )}
    </div>
  )
}

function PlanView({ caseId, onBack }: { caseId: string; onBack: () => void }) {
  const [plan, setPlan] = useState<MvpPlan | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getMvpPlan(caseId).then(setPlan).catch((e) =>
      setError(e instanceof Error ? e.message : 'Could not load the MVP plan'))
  }, [caseId])
  useEffect(() => { load() }, [load])

  if (error) return <p className="error">{error}</p>
  if (!plan) return <p className="muted">Loading…</p>

  const doneCount = plan.stage_order.filter((s) => plan.stages[s]?.status === 'complete').length
  return (
    <section>
      <button className="secondary" onClick={onBack}>← All MVP candidates</button>
      <div className="card">
        <div className="card-header">
          <h2>{plan.case.title}</h2>
          <span className="muted small">{doneCount}/{plan.stage_order.length} stages complete</span>
        </div>
        <p className="muted small">
          Grounded in this case: {money(plan.case.annual_benefit)}/yr benefit
          ({plan.case.benefit_basis.replace(/_/g, ' ')}) · NPV {money(plan.case.npv)}
          {plan.case.roi_pct != null && <> · ROI {plan.case.roi_pct}%</>}
          {plan.case.payback_months != null && <> · payback {plan.case.payback_months} mo</>}
          {' '}— every stage pack is drafted from these numbers, and Validate closes the loop
          by measuring against them.
        </p>
        <div className="row" style={{ gap: '0.3rem', flexWrap: 'wrap' }}>
          {plan.stage_order.map((s, i) => {
            const done = plan.stages[s]?.status === 'complete'
            const current = plan.current_stage === s && !done
            return (
              <span key={s}
                    className={done ? 'pill act-verify' : current ? 'pill act-intervene' : 'pill'}>
                {i + 1}. {plan.stage_meta[s].label}{done ? ' ✓' : ''}
              </span>
            )
          })}
        </div>
      </div>
      {plan.stage_order.map((s) => (
        <StagePanel key={`${s}-${plan.updated_at}`} plan={plan} stage={s} onChanged={load} />
      ))}
    </section>
  )
}

export default function MvpStudio() {
  const [rows, setRows] = useState<MvpOverviewRow[] | null>(null)
  const [open, setOpen] = useState<string | null>(
    () => localStorage.getItem('ivd_mvp_case'))

  const load = useCallback(() => {
    getMvpOverview().then((r) => setRows(r.cases)).catch(() => setRows([]))
  }, [])
  useEffect(() => { load() }, [load])

  const openCase = (id: string | null) => {
    setOpen(id)
    if (id) localStorage.setItem('ivd_mvp_case', id)
    else localStorage.removeItem('ivd_mvp_case')
    if (!id) load()
  }

  if (open) return <PlanView caseId={open} onBack={() => openCase(null)} />

  return (
    <section>
      <div className="section-header">
        <h2>MVP Studio</h2>
        <p className="muted">
          Take an approved business case to a validated MVP: Design → Build → Test → Deploy →
          Validate. AI drafts each stage's working pack — PRD, build plan, test suite, runbook,
          go-to-market — from the case's own financials, and Validate measures the result
          against the claimed benefit.
        </p>
      </div>
      {rows == null && <p className="muted">Loading…</p>}
      {rows != null && rows.length === 0 && (
        <div className="card">
          <p className="muted">No business cases yet. An MVP starts from an approved case —
            develop an idea into a case under Approvals, then plan its MVP here.</p>
        </div>
      )}
      {rows != null && rows.length > 0 && (
        <div className="card">
          {rows.map((r) => (
            <div key={r.case_id} className="decision-row">
              <span className={r.mvp_started ? 'pill act-verify' : 'pill'}>
                {r.mvp_started ? `${r.mvp_done}/${r.mvp_total} · ${r.mvp_current_stage}` : 'not started'}
              </span>
              <span style={{ flex: 1 }}>
                <strong>{r.title}</strong>{' '}
                <span className="muted small">case stage: {r.stage.replace(/_/g, ' ')}
                  {r.benefit != null && <> · {money(r.benefit)}/yr claimed</>}</span>
              </span>
              <button className="secondary" onClick={() => openCase(r.case_id)}>
                {r.mvp_started ? 'Continue MVP' : 'Plan the MVP'}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
