export interface SourceStatus {
  source_type: string
  label: string
  required_columns: string[]
  rows_loaded: number
  origin: string | null
  updated_at: string | null
}

export interface Opportunity {
  id: string
  source: string
  category: string
  title: string
  description: string
  estimated_annual_savings: number
  effort: 'low' | 'medium' | 'high'
  confidence: 'low' | 'medium' | 'high'
  affected_items: string[]
  affected_count: number
}

export interface KPI {
  name: string
  formula: string
  baseline_method: string
  target: string
  data_sources: string[]
  cadence: string
  indicator_type: string
}

export interface ValueDriver {
  name: string
  driver_type: string
  description: string
}

export interface ROIPlan {
  summary: string
  value_drivers: ValueDriver[]
  kpis: KPI[]
  baseline_plan: string
  roi_formula: string
  measurement_cadence: string
  measurement_duration: string
  assumptions: string[]
  measurement_risks: string[]
}

export interface LinkedOpportunity {
  id: string
  title: string
  category: string
  source: string
  estimated_annual_savings: number
  description: string
}

export interface KpiReading {
  id: number
  kpi_name: string
  reading_date: string
  value: number
  note: string | null
}

export interface SavingsEntry {
  id: number
  entry_date: string
  amount: number
  note: string | null
}

export interface Tracking {
  total_realized_savings: number
  realized_roi_pct: number | null
  payback_progress_pct: number | null
  months_live: number | null
  readings_count: number
}

export interface BusinessCase {
  id: string
  title: string
  description: string
  estimated_cost: number | null
  submitted_at: string
  roi_plan: ROIPlan
  generated_by: 'claude' | 'template'
  note: string | null
  linked_opportunity: LinkedOpportunity | null
  status: 'proposed' | 'implemented'
  go_live_date: string | null
  kpi_readings: KpiReading[]
  savings_entries: SavingsEntry[]
  tracking: Tracking | null
}
