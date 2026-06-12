export interface SourceStatus {
  source_type: string
  label: string
  required_columns: string[]
  rows_loaded: number
  origin: string | null
  updated_at: string | null
}

export type Quadrant = 'quick_win' | 'strategic_bet' | 'fill_in' | 'deprioritize'

export type Complexity = 'low' | 'medium' | 'high' | 'very_high'

export interface Priority {
  score: number
  rank: number
  quadrant: Quadrant
  risk_adjusted_annual_savings: number
  est_implementation_cost: number
  time_to_value_months: number
  payback_months: number | null
  first_year_net: number
  three_year_net: number
  payback_ratio: number
  components: { value: number; efficiency: number; speed: number; simplicity: number }
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
  complexity: Complexity
  affected_items: string[]
  affected_count: number
  priority: Priority
}

export interface Weights {
  value: number
  efficiency: number
  speed: number
  simplicity: number
}

export interface PrioritizationSummary {
  total_risk_adjusted_annual_savings: number
  count_for_80_pct_of_value: number
  quadrant_counts: Partial<Record<Quadrant, number>>
}

export interface KPI {
  name: string
  formula: string
  baseline_method: string
  target: string
  data_sources: string[]
  cadence: string
  indicator_type: string
  objectivity?: 'hard' | 'medium' | 'soft'
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
  unmeasurable_claims?: string[]
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
  measured_annual_savings: number
  realized_roi_pct: number | null
  payback_progress_pct: number | null
  months_live: number | null
  readings_count: number
}

export interface MetricObservation {
  id: number
  observed_at: string
  value: number
  rows_matched: number
}

export interface MetricBinding {
  id: number
  kpi_name: string | null
  label: string
  definition: Record<string, unknown>
  unit: string
  baseline_value: number
  baseline_rows: number
  baseline_captured_at: string
  observations: MetricObservation[]
  latest_value: number | null
  delta: number | null
  annualized_delta: number | null
}

export interface CalibrationCategory {
  cases: number
  forecast_annual_savings: number
  actual_annual_savings: number
  realization_rate: number
  applied_factor: number
  basis: string[]
}

export interface CalibrationReport {
  categories: Record<string, CalibrationCategory>
  cases_observed: number
}

export interface DashboardData {
  funnel: {
    identified_annual_savings: number
    risk_adjusted_annual_savings: number
    committed_annual_savings: number
    measured_annual_savings: number
    claimed_savings_to_date: number
  }
  opportunities: {
    count: number
    quadrants: Record<string, { count: number; value: number }>
    top: {
      id: string
      title: string
      score: number
      estimated_annual_savings: number
      quadrant: Quadrant
      complexity: Complexity
    }[]
    count_for_80_pct_of_value: number
  }
  pipeline: {
    id: string
    title: string
    status: 'proposed' | 'implemented'
    go_live_date: string | null
    forecast_annual_savings: number | null
    measured_annual_savings: number | null
    claimed_savings: number | null
    payback_progress_pct: number | null
  }[]
  timeline: {
    months: TimelineMonth[]
    summary: TimelineSummary | null
  }
  calibration: CalibrationReport
  sources: {
    source_type: string
    rows_loaded: number
    origin: string | null
    updated_at: string | null
  }[]
}

export interface TimelineMonth {
  month: string
  cumulative_cost: number
  cumulative_claimed: number
  cumulative_verified: number
  verified_run_rate: number
  roi_pct: number | null
  projected: boolean
}

export interface TimelineSummary {
  total_invested: number
  verified_value_to_date: number
  claimed_value_to_date: number
  verified_run_rate: number
  portfolio_roi_pct: number | null
  break_even_month: string | null
  break_even_projected: boolean
}

export interface PortfolioFinding {
  category: string
  severity: 'high' | 'medium' | 'low'
  title: string
  description: string
  affected_initiatives: string[]
  affected_count: number
  value_impact: number
}

export interface PortfolioReport {
  health_score: number
  stats: {
    initiatives: number
    total_budget: number
    total_spend_to_date: number
    total_claimed_annual_benefit: number
    total_measured_annual_benefit: number
    verification_ratio: number | null
  }
  findings: PortfolioFinding[]
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
  metric_bindings: MetricBinding[]
  tracking: Tracking | null
}
