import type { BusinessCase, Opportunity, SourceStatus } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json()
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

export function getOpportunities() {
  return request<{
    opportunities: Opportunity[]
    total_estimated_annual_savings: number
  }>('/api/opportunities')
}

export function submitBusinessCase(body: {
  title: string
  description: string
  estimated_cost: number | null
}) {
  return request<BusinessCase>('/api/business-cases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function getBusinessCases() {
  return request<{ business_cases: BusinessCase[] }>('/api/business-cases')
}

export const money = (n: number) =>
  n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
