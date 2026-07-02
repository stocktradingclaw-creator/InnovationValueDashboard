import { useRef, useState } from 'react'
import { useEffect } from 'react'
import { commentOnIdea, evaluateIdea, getChallenges, getInitiatives, getNotifications, importIdeas, money, submitIdea, voteIdea } from '../api'
import type { Challenge, Idea, Initiative, Notification } from '../types'

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

const BENEFIT_GLYPHS: Record<string, [string, string]> = {
  cost_reduction: ['▼', 'g-cost'],
  revenue_growth: ['↗', 'g-rev'],
  risk_avoidance: ['⛨', 'g-risk'],
  experience: ['♥', 'g-exp'],
  strategic: ['♟', 'g-strat'],
}

const BENEFIT_TYPES = [
  ['cost_reduction', 'Cost reduction'],
  ['revenue_growth', 'Revenue growth'],
  ['risk_avoidance', 'Risk avoidance'],
  ['experience', 'Customer/employee experience'],
  ['strategic', 'Strategic capability'],
]

function SubmitForm({ challenges, initiatives, onChanged }: { challenges: Challenge[]; initiatives: Initiative[]; onChanged: () => void }) {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [submitter, setSubmitter] = useState('')
  const [category, setCategory] = useState('')
  const [benefit, setBenefit] = useState('')
  const [benefitType, setBenefitType] = useState('')
  const [challengeId, setChallengeId] = useState('')
  const [initiativeId, setInitiativeId] = useState('')
  const [beneficiary, setBeneficiary] = useState('')
  const [painPoint, setPainPoint] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const activeChallenges = challenges.filter((c) => c.status === 'active')

  // prompt for the information that improves the triage score
  const prompts: string[] = []
  if (title && description.length > 0 && description.length < 80)
    prompts.push('Add more detail to the description (what problem, who benefits, how) — short descriptions score lower.')
  if (title && !benefit) prompts.push('An annual benefit estimate (even rough) sharpens prioritization; without one the hub derives it from matched data.')
  if (title && !category) prompts.push('A category helps routing; the hub will derive one from matched opportunities if omitted.')
  if (title && !submitter) prompts.push('Add your name so reviewers can follow up.')
  if (title && !beneficiary) prompts.push('Who is this for? Ideas anchored to a named beneficiary score higher on desirability.')
  if (title && !painPoint) prompts.push('What human pain does this solve? Describing the problem people feel is the strongest signal reviewers look for.')

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
        benefit_type: benefitType || undefined,
        challenge_id: challengeId || undefined,
        initiative_id: initiativeId || undefined,
        beneficiary: beneficiary || undefined,
        pain_point: painPoint || undefined,
      })
      setTitle(''); setDescription(''); setSubmitter(''); setCategory(''); setBenefit('')
      setBenefitType(''); setChallengeId(''); setInitiativeId(''); setBeneficiary(''); setPainPoint('')
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
      </div>
      <div className="row">
        <input
          placeholder="Who is this for? (beneficiary)"
          value={beneficiary}
          onChange={(e) => setBeneficiary(e.target.value)}
        />
        <input
          placeholder="What pain does it solve for them?"
          value={painPoint}
          onChange={(e) => setPainPoint(e.target.value)}
        />
      </div>
      <div className="row">
        <select value={benefitType} onChange={(e) => setBenefitType(e.target.value)}>
          <option value="">Benefit type (hub will default to cost reduction)</option>
          {BENEFIT_TYPES.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </select>
        {initiatives.length > 0 && (
          <select value={initiativeId} onChange={(e) => setInitiativeId(e.target.value)}>
            <option value="">No strategic initiative</option>
            {initiatives.map((i) => (
              <option key={i.id} value={i.id}>Initiative: {i.name}</option>
            ))}
          </select>
        )}
        {activeChallenges.length > 0 && (
          <select value={challengeId} onChange={(e) => setChallengeId(e.target.value)}>
            <option value="">Not answering a challenge</option>
            {activeChallenges.map((c) => (
              <option key={c.id} value={c.id}>Challenge: {c.title}</option>
            ))}
          </select>
        )}
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
      <div className="card-header clickable" role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(!expanded) } }} onClick={() => setExpanded(!expanded)}>
        <div className="idea-identity">
          <span className={`benefit-glyph ${BENEFIT_GLYPHS[idea.benefit_type ?? 'cost_reduction']?.[1] ?? 'g-cost'}`} aria-hidden="true">
            {BENEFIT_GLYPHS[idea.benefit_type ?? 'cost_reduction']?.[0] ?? '▼'}
          </span>
          <span className="avatar" aria-hidden="true">{(idea.submitter ?? '?').slice(0, 1).toUpperCase()}</span>
        <div>
          <h3>{idea.title}</h3>
          <p className="muted small">
            {idea.submitter ?? 'anonymous'} · {idea.submitted_at.slice(0, 10)} ·{' '}
            {idea.source === 'import' ? 'imported backlog' : 'submitted'} ·{' '}
            {idea.category ?? 'uncategorized'}
            {idea.benefit_type ? ` · ${idea.benefit_type.replace('_', ' ')}` : ''}
            {idea.horizon ? ` · ${idea.horizon.toUpperCase()}` : ''}
          </p>
        </div>
        </div>
        <div className="row">
          {a && (
            <span className="score-ring" title={`Triage score ${a.score}`}>
              <svg viewBox="0 0 36 36" aria-hidden="true">
                <circle className="gauge-bg" cx="18" cy="18" r="14" pathLength={100} />
                <circle className={`gauge-fg ${a.score >= 60 ? 'g-good' : a.score >= 35 ? 'g-warn' : 'g-bad'}`}
                        cx="18" cy="18" r="14" pathLength={100} strokeDasharray={`${a.score} 100`} />
              </svg>
              <b>{Math.round(a.score)}</b>
            </span>
          )}
          {a && <span className={`pill rec-${a.recommendation}`}>{REC_LABELS[a.recommendation] ?? a.recommendation}</span>}
          <span className={idea.status === 'business_case' ? 'badge badge-ok' : 'badge'}>{idea.status.replace('_', ' ')}</span>
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
            {a.score_components.desirability != null && <> · desirability {a.score_components.desirability}</>}
          </p>
          {(idea.beneficiary || idea.pain_point) && (
            <p className="small">
              {idea.beneficiary && <><strong>For:</strong> {idea.beneficiary} </>}
              {idea.pain_point && <><strong>· Pain:</strong> {idea.pain_point}</>}
            </p>
          )}
          {a.possible_duplicates && a.possible_duplicates.length > 0 && (
            <div className="banner-warn">
              Possible duplicate of{' '}
              {a.possible_duplicates.map((d) => `${d.title} (${Math.round(d.similarity * 100)}%)`).join(', ')}
            </div>
          )}
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
          {['proposed', 'qualified', 'prioritized'].includes(idea.status) && (
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
          <Social idea={idea} onChanged={onChanged} />
        </div>
      )}
    </div>
  )
}

function Social({ idea, onChanged }: { idea: Idea; onChanged: () => void }) {
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [buildOn, setBuildOn] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  return (
    <div className="social-box">
      {idea.comments.map((c) => (
        <div key={c.id} className="small comment-row">
          <span className={c.build_on ? 'pill act-approve' : 'pill act-verify'}>
            {c.build_on ? 'build-on' : 'comment'}
          </span>{' '}
          <strong>{c.author}</strong> <span className="muted">{c.comment}</span>
        </div>
      ))}
      <div className="row">
        <input placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 140 }} />
        <input
          placeholder='Add a comment — or check "build on" to extend the idea'
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <label className="small muted" style={{ whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={buildOn} onChange={(e) => setBuildOn(e.target.checked)} style={{ width: 'auto' }} />{' '}
          build on
        </label>
        <button
          className="secondary"
          disabled={!!busy || !name.trim() || !text.trim()}
          onClick={async () => {
            setBusy('comment')
            try {
              await commentOnIdea(idea.id, { author: name, comment: text, build_on: buildOn })
              setText(''); setBuildOn(false)
              onChanged()
            } finally {
              setBusy(null)
            }
          }}
        >
          {busy === 'comment' ? '…' : 'Post'}
        </button>
        <button
          className="secondary"
          disabled={!!busy || !name.trim()}
          title="Votes are signal for reviewers, never the decision"
          onClick={async () => {
            setBusy('vote')
            try {
              await voteIdea(idea.id, name)
              onChanged()
            } finally {
              setBusy(null)
            }
          }}
        >
          {busy === 'vote' ? '…' : `▲ ${idea.vote_count}`}
        </button>
      </div>
    </div>
  )
}

export default function Ideas({ ideas, onChanged }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState('all')
  const [who, setWho] = useState('')
  const [challenges, setChallenges] = useState<Challenge[]>([])
  const [initiatives, setInitiatives] = useState<Initiative[]>([])
  const [initiativeFilter, setInitiativeFilter] = useState('all')
  const [notifyName, setNotifyName] = useState('')
  const [notifications, setNotifications] = useState<Notification[] | null>(null)

  useEffect(() => {
    getChallenges().then((r) => setChallenges(r.challenges)).catch(() => {})
    getInitiatives().then((r) => setInitiatives(r.initiatives)).catch(() => {})
  }, [ideas.length])

  const filtered = ideas.filter((i) => {
    if (filter !== 'all' && i.status !== filter) return false
    if (initiativeFilter !== 'all' && i.initiative_id !== initiativeFilter) return false
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

      {challenges.filter((c) => c.status === 'active').length > 0 && (
        <div className="row filter-row">
          {challenges.filter((c) => c.status === 'active').map((c) => (
            <span key={c.id} className="badge badge-ok" title={c.question}>
              Active challenge: {c.title} ({c.ideas_count} ideas)
            </span>
          ))}
        </div>
      )}

      <SubmitForm challenges={challenges} initiatives={initiatives} onChanged={onChanged} />

      <div className="card">
        <div className="row">
          <span className="muted small">Your updates:</span>
          <input
            placeholder="enter your name to see decisions on your ideas"
            value={notifyName}
            onChange={(e) => setNotifyName(e.target.value)}
            style={{ maxWidth: 320 }}
          />
          <button
            className="secondary"
            disabled={!notifyName.trim()}
            onClick={async () =>
              setNotifications((await getNotifications(notifyName)).notifications)
            }
          >
            Check
          </button>
        </div>
        {notifications !== null && (
          notifications.length === 0 ? (
            <p className="muted small">No updates yet for {notifyName}.</p>
          ) : (
            <ul className="muted small">
              {notifications.map((n) => (
                <li key={n.id}>{n.created_at.slice(0, 10)} — {n.message}</li>
              ))}
            </ul>
          )
        )}
      </div>

      {initiatives.length > 0 && (
        <div className="row filter-row">
          <span className="muted small">Group by initiative:</span>
          <button
            className={initiativeFilter === 'all' ? 'chip chip-active' : 'chip'}
            onClick={() => setInitiativeFilter('all')}
          >
            All
          </button>
          {initiatives.map((i) => (
            <button
              key={i.id}
              className={initiativeFilter === i.id ? 'chip chip-active' : 'chip'}
              onClick={() => setInitiativeFilter(i.id)}
              title={i.objective}
            >
              {i.name} ({i.ideas_count})
            </button>
          ))}
        </div>
      )}

      <div className="row filter-row">
        {['all', 'proposed', 'qualified', 'prioritized', 'business_case', 'backlog', 'declined'].map((s) => (
          <button key={s} className={filter === s ? 'chip chip-active' : 'chip'} onClick={() => setFilter(s)}>
            {s === 'all' ? `All (${ideas.length})` : s.replace('_', ' ')}
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
