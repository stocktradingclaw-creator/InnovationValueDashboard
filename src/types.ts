export interface SourceStatus {
  source_type: string
  label: string
  required_columns: string[]
  rows_loaded: number
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

export interface BusinessCase {
  id: string
  title: string
  description: string
  estimated_cost: number | null
  submitted_at: string
  roi_plan: ROIPlan
  generated_by: 'claude' | 'template'
  note: string | null
}
