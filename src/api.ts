import type { BusinessCase, Opportunity, SourceStatus } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
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

export interface UserProfile { name: string; role: string }

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
  decision: 'approve' | 'reject' | 'feedback' | 'experiment' | 'qualify' | 'prioritize' | 'hold' | 'develop' | 'advance'
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
