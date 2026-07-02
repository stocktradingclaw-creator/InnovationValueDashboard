import { useRef, useState } from 'react'
import { evaluateIdea, importIdeas, money, submitIdea } from '../api'
import type { Idea } from '../types'

interface Props {
  ideas: Idea[]
  onChanged: () => void
}

const REC_LABELS: Record<string, string> = {
  fast_track: 'Fast-track',
  business_case: 'Business case',
  investigate: 'Investigate',
  needs_info: 'Needs info',
}

function SubmitForm({ onChanged }: { onChanged: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitter, setSubmitter] = useState('')
  const [category, setCategory] = useState('')
  const [benefit, setBenefit] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // prompt for the information that improves the triage score
  const prompts: string[] = []
  if (title && description.length > 0 && description.length < 80)
    prompts.push('Add more detail to the description (what problem, who benefits, how) — short descriptions score lower.')
  if (title && !benefit) prompts.push('An annual benefit estimate (even rough) sharpens prioritization; without one the hub derives it from matched data.')
  if (title && !category) prompts.push('A category helps routing; the hub will derive one from matched opportunities if omitted.')
  if (title && !submitter) prompts.push('Add your name so reviewers can follow up.')

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      await submitIdea({
        title,
        description,
        submitter: submitter || undefined,
        category: category || undefined,
        estimated_annual_benefit: benefit ? Number(benefit) : null,
      })
      setTitle(''); setDescription(''); setSubmitter(''); setCategory(''); setBenefit('')
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card bc-form">
      <h3>Submit an idea</h3>
      <input placeholder="Title — what's the idea in one line?" value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea
        rows={4}
        placeholder="Describe the problem, the proposed change, and who benefits…"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <div className="row">
        <input placeholder="Your name" value={submitter} onChange={(e) => setSubmitter(e.target.value)} />
        <input placeholder="Category (optional)" value={category} onChange={(e) => setCategory(e.target.value)} />
        <input type="number" placeholder="Est. annual benefit $ (optional)" value={benefit} onChange={(e) => setBenefit(e.target.value)} />
        <button disabled={busy || !title.trim() || !description.trim()} onClick={submit}>
          {busy ? 'Triaging…' : 'Submit idea'}
        </button>
      </div>
      {prompts.length > 0 && (
        <ul className="muted small prompt-list">
          {prompts.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function IdeaCard({ idea, onChanged }: { idea: Idea; onChanged: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const a = idea.assessment

  const act = async (what: 'evaluate') => {
    setBusy(what)
    try {
      await evaluateIdea(idea.id)
      onChanged()
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="card idea-card">
      <div className="card-header clickable" onClick={() => setExpanded(!expanded)}>
        <div>
          <h3>{idea.title}</h3>
          <p className="muted small">
            {idea.submitter ?? 'anonymous'} · {idea.submitted_at.slice(0, 10)} ·{' '}
            {idea.source === 'import' ? 'imported backlog' : 'submitted'} ·{' '}
            {idea.category ?? 'uncategorized'}
          </p>
        </div>
        <div className="row">
          {a && <span className="score-chip">{a.score}</span>}
          {a && <span className={`pill rec-${a.recommendation}`}>{REC_LABELS[a.recommendation] ?? a.recommendation}</span>}
          <span className={idea.status === 'promoted' ? 'badge badge-ok' : 'badge'}>{idea.status}</span>
        </div>
      </div>

      {expanded && a && (
        <div className="plan">
          <p>{idea.description}</p>
          <p><strong>Triage:</strong> {a.rationale}</p>
          {a.matched_opportunity && (
            <p className="muted small">
              Matched: {a.matched_opportunity.title} ({money(a.matched_opportunity.estimated_annual_savings)}/yr)
            </p>
          )}
          <p className="muted small">
            Score {a.score} — impact {a.score_components.impact} · grounding {a.score_components.data_grounding} ·
            alignment {a.score_components.alignment} · completeness {a.score_components.completeness}
          </p>
          {a.enrichment.length > 0 && (
            <p className="muted small">Enrichment: {a.enrichment.join(' ')}</p>
          )}
          {a.guardrail_flags.length > 0 && (
            <div className="banner-warn">
              {a.guardrail_flags.map((f) => <div key={f}>{f}</div>)}
            </div>
          )}
          {a.ai_evaluation && (
            <div className={a.ai_evaluation.validated ? 'banner-ok' : 'banner-warn'}>
              <strong>AI evaluation ({a.ai_evaluation.generated_by}):</strong>{' '}
              {a.ai_evaluation.validation_notes}
              {a.ai_evaluation.missing_information.length > 0 && (
                <div className="small">Missing: {a.ai_evaluation.missing_information.join('; ')}</div>
              )}
            </div>
          )}
          {idea.status === 'triaged' && (
            <div className="row">
              <button className="secondary" disabled={busy === 'evaluate'} onClick={() => act('evaluate')}>
                {busy === 'evaluate' ? 'Evaluating…' : 'AI evaluate'}
              </button>
              <span className="muted small">Approve / reject in the Command Center.</span>
            </div>
          )}
          {idea.promoted_case_id && (
            <p className="muted small">Promoted to case {idea.promoted_case_id}.</p>
          )}
        </div>
      )}
    </div>
  )
}

export default function Ideas({ ideas, onChanged }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [who, setWho] = useState('')

  const filtered = ideas.filter((i) => {
    if (filter !== 'all' && i.status !== filter) return false
    if (who && !(i.submitter ?? '').toLowerCase().includes(who.toLowerCase())) return false
    return true
  })

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Idea intake</h2>
          <p className="muted">
            Every idea is automatically validated, scored under the leadership scoring framework,
            matched against detected opportunities, and enriched where intake was incomplete.
          </p>
        </div>
        <div>
          <input
            ref={fileInput}
            type="file"
            accept=".csv"
            style={{ display: 'none' }}
            onChange={async (e) => {
              const file = e.target.files?.[0]
              if (!file) return
              setImportBusy(true)
              setImportMsg(null)
              try {
                const res = await importIdeas(file)
                setImportMsg(`Imported ${res.imported} ideas (${res.skipped} skipped).`)
                onChanged()
              } catch (err) {
                setImportMsg(err instanceof Error ? err.message : String(err))
              } finally {
                setImportBusy(false)
                if (fileInput.current) fileInput.current.value = ''
              }
            }}
          />
          <button className="secondary" disabled={importBusy} onClick={() => fileInput.current?.click()}>
            {importBusy ? 'Importing…' : 'Import existing backlog (CSV)'}
          </button>
          {importMsg && <p className="muted small">{importMsg}</p>}
        </div>
      </div>

      <SubmitForm onChanged={onChanged} />

      <div className="row filter-row">
        {['all', 'triaged', 'promoted', 'declined'].map((s) => (
          <button key={s} className={filter === s ? 'chip chip-active' : 'chip'} onClick={() => setFilter(s)}>
            {s === 'all' ? `All (${ideas.length})` : s}
          </button>
        ))}
        <input placeholder="Filter by submitter…" value={who} onChange={(e) => setWho(e.target.value)} style={{ maxWidth: 220 }} />
      </div>

      {filtered.length === 0 ? (
        <p className="muted">No ideas yet — submit one above or import a backlog.</p>
      ) : (
        filtered.map((i) => <IdeaCard key={i.id} idea={i} onChanged={onChanged} />)
      )}
    </section>
  )
}
