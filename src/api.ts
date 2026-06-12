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

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
