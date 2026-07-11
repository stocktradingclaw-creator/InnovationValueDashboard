import type { BusinessCase, Opportunity, SourceStatus } from './types'

// Wrap window.fetch once: any same-origin /api call gets the bearer token,
// and 401s trigger the auth-required flow. Raw fetch() in components is then
// safe by construction.
const _rawFetch = window.fetch.bind(window)
window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
  if (url.startsWith('/api')) {
    const token = localStorage.getItem('ivd_token')
    const headers = new Headers(init?.headers ?? (typeof input === 'object' && 'headers' in input ? (input as Request).headers : undefined))
    if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`)
    const res = await _rawFetch(input, { ...init, headers })
    if (res.status === 401 && !url.startsWith('/api/auth')) {
      window.dispatchEvent(new Event('ivd-auth-required'))
    }
    return res
  }
  return _rawFetch(input, init)
}) as typeof window.fetch

export function exportUrl(path: string): string {
  const token = localStorage.getItem('ivd_token')
  if (!token) return path
  return path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(token)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('ivd_token')
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(path, { ...init, headers })
  if (res.status === 401 && !path.startsWith('/api/auth')) {
    localStorage.removeItem('ivd_token')
    window.dispatchEvent(new Event('ivd-auth-required'))
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const detail = body?.detail
    throw new Error(
      typeof detail === 'string' ? detail : (JSON.stringify(detail) ?? `${res.status} ${res.statusText}`),
    )
  }
  return res.json()
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface Me { auth_required: boolean; user: { name: string; role: string } | null }

export function getMe() {
  return request<Me>('/api/auth/me')
}

export async function login(name: string, password: string) {
  const r = await request<{ token: string; user: { name: string; role: string } }>(
    '/api/auth/login', json({ name, password }))
  localStorage.setItem('ivd_token', r.token)
  localStorage.setItem('ivd_user', r.user.name)
  return r.user
}

export async function logout() {
  await request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }).catch(() => {})
  localStorage.removeItem('ivd_token')
}

export function seedLifecycle() {
  return request<{ seeded: boolean; ideas: number; cases: number; note: string }>(
    '/api/demo/seed-lifecycle', { method: 'POST' })
}

export function similarIdeas(q: string) {
  return request<{ similar: { id: string; title: string; status: string; submitter: string | null; vote_count: number }[] }>(
    `/api/ideas/similar?q=${encodeURIComponent(q)}`)
}

export function searchAll(q: string) {
  return request<{ results: { type: string; tab: string; id: string; title: string; hint: string }[] }>(
    `/api/search?q=${encodeURIComponent(q)}`)
}

export function getIdeaAttachments(id: string) {
  return request<{ attachments: { id: number; filename: string; size: number; uploaded_by: string | null }[] }>(
    `/api/ideas/${id}/attachments`)
}

export function uploadIdeaAttachment(id: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ id: number; filename: string }>(`/api/ideas/${id}/attachments`,
    { method: 'POST', body: form })
}

export function reviewIdea(id: string, body: { reviewer: string; scores: Record<string, number>; comment?: string }) {
  return request<{ summary: { count: number; average: number | null } }>(
    `/api/ideas/${id}/reviews`, json(body))
}

export function getMyWork(user: string) {
  return request<{ items: { kind: string; id: string; title: string; tab: string; age_days: number; what: string }[] }>(
    `/api/my-work?user=${encodeURIComponent(user)}`)
}

export function getNotificationSettings() {
  return request<{ webhook: string }>('/api/settings/notifications')
}

export function putNotificationSettings(webhook: string) {
  return request<{ webhook: string }>(`/api/settings/notifications${actorQS()}`,
    { ...json({ webhook }), method: 'PUT' })
}

export function getPnl() {
  return request<Record<string, unknown> & { capital_deployed: number; verified_annual_return: number;
    claimed_savings_to_date: number; forecast_book_raw: number; forecast_book_calibrated: number;
    tuition_paid: number; tuition_lessons: { title: string; learning: string | null }[] }>(
    '/api/reports/innovation-pnl')
}

export function redTeamCase(id: string) {
  return request<{ red_team: { killer_assumption: string; failure_modes: string[];
    hidden_costs: string[]; cannibalization: string; recommendation: string; generated_by: string } }>(
    `/api/business-cases/${id}/redteam`, { method: 'POST' })
}

export function runSimulator(caseIds?: string[]) {
  return request<{ cases: number; trials: number; annual_value_p10: number; annual_value_p50: number;
    annual_value_p90: number; probability_positive: number;
    per_case: { id: string; title: string; p50: number }[] }>(
    '/api/simulator', json({ case_ids: caseIds }))
}

export function getGenome() {
  return request<{ baseline_promotion_rate: number; ideas: number;
    traits: { trait: string; sample: number; multiplier: number; low_confidence: boolean }[] }>(
    '/api/genome')
}

export function getDividends() {
  return request<{ dividends: { case_id: string; case_title: string; citations: number }[] }>(
    '/api/learning-dividends')
}

export function radarScan(topic: string, launch = false) {
  return request<{ challenge: { id: string; title: string } | null; signals: string[];
    draft: { challenge_title: string }; starter_ideas: string[]; generated_by: string }>(
    '/api/radar/scan', json({ topic, launch }))
}

export function requestAccess(name: string, note?: string) {
  return request<{ ok: boolean; admins_notified: number }>('/api/auth/request-access',
    json({ name, note }))
}

export function getDatasets() {
  return request<{ sources: SourceStatus[] }>('/api/datasets')
}

export function loadSamples() {
  return request<{ loaded: Record<string, number> }>('/api/datasets/load-samples', {
    method: 'POST',
  })
}

export function uploadDataset(sourceType: string, file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ source_type: string; rows_loaded: number }>(
    `/api/datasets/${sourceType}`,
    { method: 'POST', body: form },
  )
}

export function clearDataset(sourceType: string) {
  return request<{ source_type: string }>(`/api/datasets/${sourceType}`, {
    method: 'DELETE',
  })
}

export function syncServiceNow(body: {
  instance_url: string
  username: string
  password: string
  source: 'cmdb' | 'itsm'
}) {
  return request<{ source_type: string; rows_loaded: number }>(
    '/api/connectors/servicenow/sync',
    json(body),
  )
}

export function syncSap(body: {
  service_url: string
  entity_set: string
  username?: string
  password?: string
}) {
  return request<{ source_type: string; rows_loaded: number }>(
    '/api/connectors/sap/sync',
    json(body),
  )
}

export function getOpportunities(weights?: {
  value: number
  efficiency: number
  speed: number
  simplicity: number
}) {
  const qs = weights
    ? `?value_weight=${weights.value}&efficiency_weight=${weights.efficiency}` +
      `&speed_weight=${weights.speed}&simplicity_weight=${weights.simplicity}`
    : ''
  return request<{
    opportunities: Opportunity[]
    total_estimated_annual_savings: number
    prioritization: {
      weights: { value: number; efficiency: number; speed: number; simplicity: number }
      summary: import('./types').PrioritizationSummary | null
    }
  }>(`/api/opportunities${qs}`)
}

export function submitBusinessCase(body: {
  title: string
  description: string
  estimated_cost: number | null
  linked_opportunity_id: string | null
}) {
  return request<BusinessCase>('/api/business-cases', json(body))
}

export interface MvpArtifact {
  summary: string
  sections: { title: string; detail: string }[]
  checklist: string[]
  ai_leverage: string[]
  generated_by: 'claude' | 'template'
}

export interface MvpStageState {
  status: 'pending' | 'in_progress' | 'complete'
  artifact: MvpArtifact | null
  note: string | null
  completed_at: string | null
  completed_by: string | null
}

export interface MvpPlan {
  case_id: string
  current_stage: string
  stages: Record<string, MvpStageState>
  updated_at: string | null
  stage_order: string[]
  stage_meta: Record<string, { label: string; goal: string; ai_role: string }>
  case: {
    id: string; title: string; stage: string; annual_benefit: number
    npv: number; roi_pct: number | null; payback_months: number | null
    benefit_basis: string
  }
}

export interface MvpOverviewRow {
  case_id: string; title: string; stage: string; status: string
  benefit: number | null; mvp_started: boolean
  mvp_current_stage: string | null; mvp_done: number; mvp_total: number
}

export function getMvpOverview() {
  return request<{ stages: string[]; stage_meta: Record<string, { label: string; goal: string; ai_role: string }>; cases: MvpOverviewRow[] }>(
    '/api/mvp')
}

export function getMvpPlan(caseId: string) {
  return request<MvpPlan>(`/api/mvp/${caseId}`)
}

export function generateMvpStage(caseId: string, stage: string) {
  return request<{ stage: string; artifact: MvpArtifact; plan: MvpPlan }>(
    `/api/mvp/${caseId}/generate`, json({ stage }))
}

export function advanceMvpStage(caseId: string, stage: string, note?: string) {
  return request<{ completed: string; plan: MvpPlan; done?: boolean; advice?: string }>(
    `/api/mvp/${caseId}/advance`, json({ stage, note }))
}

export function getBusinessCases() {
  return request<{ business_cases: BusinessCase[] }>('/api/business-cases')
}

export function implementCase(caseId: string, goLiveDate: string) {
  return request<BusinessCase>(
    `/api/business-cases/${caseId}/implement`,
    json({ go_live_date: goLiveDate }),
  )
}

export function addReading(
  caseId: string,
  body: { kpi_name: string; reading_date: string; value: number; note?: string },
) {
  return request<BusinessCase>(`/api/business-cases/${caseId}/readings`, json(body))
}

export function addSavings(
  caseId: string,
  body: { entry_date: string; amount: number; note?: string },
) {
  return request<BusinessCase>(`/api/business-cases/${caseId}/savings`, json(body))
}

export function observeBinding(caseId: string, bindingId: number) {
  return request<BusinessCase>(
    `/api/business-cases/${caseId}/bindings/${bindingId}/observe`,
    { method: 'POST' },
  )
}

export function getCalibration() {
  return request<import('./types').CalibrationReport>('/api/calibration')
}

export function getDashboard() {
  return request<import('./types').DashboardData>('/api/dashboard')
}

export function getPortfolioDiagnostic() {
  return request<import('./types').PortfolioReport>('/api/portfolio/diagnostic')
}

export interface AssistResult {
  mode: 'generate' | 'improve'
  draft: string
  suggestions: string[]
  generated_by: 'claude' | 'template'
  fields?: {
    beneficiary: string | null; pain_point: string | null
    estimated_annual_benefit: number | null; benefit_type: string | null
    category: string | null
  }
}

export function assistDescription(body: { title: string; description?: string }) {
  return request<AssistResult>('/api/ideas/assist', json(body))
}

export function submitIdea(body: {
  title: string
  description: string
  submitter?: string
  category?: string
  estimated_annual_benefit?: number | null
  benefit_type?: string
  horizon?: string
  challenge_id?: string
  beneficiary?: string
  pain_point?: string
  initiative_id?: string
  initiative_ids?: string[]
}) {
  return request<import('./types').Idea>('/api/ideas', json(body))
}

export function importIdeas(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ imported: number; skipped: number }>('/api/ideas/import', {
    method: 'POST',
    body: form,
  })
}

export function getIdeas() {
  return request<{ ideas: import('./types').Idea[] }>('/api/ideas')
}

export function evaluateIdea(id: string) {
  return request<import('./types').Idea>(`/api/ideas/${id}/evaluate`, { method: 'POST' })
}


const actorQS = () => {
  const who = localStorage.getItem('ivd_user')
  return who ? `?actor=${encodeURIComponent(who)}` : ''
}

export interface UserProfile { name: string; role: string; has_password?: boolean; password?: string }

export function getUsers() {
  return request<{ users: UserProfile[]; roles: string[]; capabilities: Record<string, string> }>('/api/users')
}

export function putUsers(users: UserProfile[]) {
  return request<{ users: UserProfile[]; roles: string[]; capabilities: Record<string, string> }>(
    `/api/users${actorQS()}`, { ...json({ users }), method: 'PUT' })
}

export function getScoringConfig() {
  return request<import('./types').ScoringConfig>('/api/scoring-config')
}

export function putScoringConfig(config: Partial<import('./types').ScoringConfig>) {
  return request<import('./types').ScoringConfig>(`/api/scoring-config${actorQS()}`, {
    ...json(config),
    method: 'PUT',
  })
}

export function getGovernance() {
  return request<{ areas: string[]; assignments: Record<string, string[]> }>('/api/governance')
}

export function putGovernance(assignments: Record<string, string[]>) {
  return request<{ areas: string[]; assignments: Record<string, string[]> }>(`/api/governance${actorQS()}`, {
    ...json(assignments),
    method: 'PUT',
  })
}

export function getCommandQueue() {
  return request<import('./types').CommandQueue>('/api/command/queue')
}

export function decide(body: {
  subject_type: 'idea' | 'case'
  subject_id: string
  decision: 'approve' | 'reject' | 'feedback' | 'experiment' | 'qualify' | 'prioritize' | 'hold' | 'develop' | 'advance' | 'resume'
  actor?: string
  comment?: string
}) {
  return request<{ result: unknown }>('/api/command/decide', json(body))
}

export function runAutomation() {
  return request<{ summary: Record<string, number> }>('/api/automation/run', { method: 'POST' })
}

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })

export function closeChallenge(id: string) {
  return request<import('./types').Challenge>(`/api/challenges/${id}/close`, { method: 'POST' })
}

export function getChallenges() {
  return request<{ challenges: import('./types').Challenge[] }>('/api/challenges')
}

export function createChallenge(body: { title: string; question: string; theme?: string }) {
  return request<import('./types').Challenge>('/api/challenges', json(body))
}

export function addExperiment(
  caseId: string,
  body: { hypothesis: string; method: string; success_criteria: string; cost?: number | null },
) {
  return request<BusinessCase>(`/api/business-cases/${caseId}/experiments`, json(body))
}

export function concludeExperiment(
  caseId: string,
  experimentId: number,
  body: { outcome: 'proceed' | 'kill' | 'pivot'; learnings: string },
) {
  return request<BusinessCase>(
    `/api/business-cases/${caseId}/experiments/${experimentId}/conclude`,
    json(body),
  )
}

export function addTranche(caseId: string, body: { label: string; amount: number; milestone: string }) {
  return request<BusinessCase>(`/api/business-cases/${caseId}/tranches`, json(body))
}

export function releaseTranche(caseId: string, trancheId: number, actor?: string) {
  return request<BusinessCase>(
    `/api/business-cases/${caseId}/tranches/${trancheId}/release`,
    json({ actor }),
  )
}

export function getNotifications(recipient: string) {
  return request<{ notifications: import('./types').Notification[] }>(
    `/api/notifications?recipient=${encodeURIComponent(recipient)}`,
  )
}

export function getPatterns() {
  return request<{ patterns: import('./types').Pattern[] }>('/api/patterns')
}

export function replicatePattern(caseId: string) {
  return request<BusinessCase>(`/api/patterns/${caseId}/replicate`, json({}))
}

export function commentOnIdea(id: string, body: { author: string; comment: string; build_on?: boolean }) {
  return request<import('./types').Idea>(`/api/ideas/${id}/comments`, json(body))
}

export function voteIdea(id: string, voter: string) {
  return request<import('./types').Idea>(`/api/ideas/${id}/vote`, json({ voter }))
}

export function getLearnings() {
  return request<{ learnings: import('./types').Learning[] }>('/api/learnings')
}

export function getInitiatives() {
  return request<{ initiatives: import('./types').Initiative[] }>('/api/initiatives')
}

export function createInitiative(body: { name: string; objective: string }) {
  return request<import('./types').Initiative>('/api/initiatives', json(body))
}

export function getDemoStatus() {
  return request<{ demo: import('./types').DemoStatus | null; industries: string[] }>(
    '/api/demo/status',
  )
}

export function demoGenerate(body: { client?: string; industry?: string; notes?: string }) {
  return request<{ demo: import('./types').DemoStatus }>('/api/demo/generate', json(body))
}

export function demoRevert() {
  return request<{ reverted: import('./types').DemoStatus }>('/api/demo/revert', {
    method: 'POST',
  })
}

export function getLifecycle() {
  return request<import('./types').Lifecycle>('/api/lifecycle')
}

export function getPipeline() {
  return request<import('./types').PipelineData>('/api/pipeline')
}

export function getWorkflow() {
  return request<{ steps: import('./types').WorkflowStep[]; forums: string[] }>('/api/workflow')
}

export function putWorkflow(steps: import('./types').WorkflowStep[]) {
  return request<{ steps: import('./types').WorkflowStep[] }>(`/api/workflow${actorQS()}`, {
    ...json({ steps }),
    method: 'PUT',
  })
}

export function updateInitiative(id: string, body: { name?: string; objective?: string }) {
  return request<import('./types').Initiative>(`/api/initiatives/${id}`, { ...json(body), method: 'PUT' })
}

export function reorderInitiatives(ids: string[]) {
  return request<{ initiatives: import('./types').Initiative[] }>('/api/initiatives/reorder', json({ ids }))
}

export function updateChallenge(id: string, body: { title?: string; question?: string; theme?: string }) {
  return request<import('./types').Challenge>(`/api/challenges/${id}`, { ...json(body), method: 'PUT' })
}

export function toast(msg: string, undo?: () => void) {
  window.dispatchEvent(new CustomEvent('ivd-toast', { detail: { msg, undo } }))
}
