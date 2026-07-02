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

export interface Decision {
  action: 'approve' | 'fund' | 'verify' | 'intervene' | 'review'
  title: string
  detail: string
  annual_value: number
  nav: 'opportunities' | 'cases' | 'tracking' | 'portfolio'
}

export type Stage =
  | 'draft' | 'proposed' | 'experiment' | 'approved' | 'in_delivery'
  | 'live' | 'value_realized' | 'scale' | 'closed'

export interface IdeaAssessment {
  matched_opportunity: {
    id: string
    title: string
    category: string
    estimated_annual_savings: number
    quadrant: string | null
  } | null
  match_strength: number
  impact_band: string
  score: number
  score_components: Record<string, number>
  derived_category: string | null
  estimated_annual_benefit: number | null
  benefit_type: string
  horizon: string
  possible_duplicates: { id: string; title: string; similarity: number }[]
  challenge_id: string | null
  guardrail_flags: string[]
  enrichment: string[]
  recommendation: string
  rationale: string
  ai_evaluation?: {
    validated: boolean
    validation_notes: string
    category: string
    missing_information: string[]
    suggested_priority: string
    duplicate_risk: string
    generated_by: string
  }
}

export interface IdeaComment {
  id: number
  author: string
  comment: string
  build_on: number
  created_at: string
}

export interface Learning {
  outcome: string
  learnings: string
  concluded_at: string
  hypothesis: string
  case_id: string
  case_title: string
}

export interface Idea {
  id: string
  title: string
  description: string
  submitter: string | null
  submitted_at: string
  status: 'proposed' | 'qualified' | 'prioritized' | 'business_case' | 'backlog' | 'declined'
  assessment: IdeaAssessment | null
  promoted_case_id: string | null
  category: string | null
  estimated_annual_benefit: number | null
  source: 'manual' | 'import'
  benefit_type: string | null
  horizon: string | null
  challenge_id: string | null
  beneficiary: string | null
  pain_point: string | null
  initiative_id: string | null
  comments: IdeaComment[]
  voters: string[]
  vote_count: number
}

export interface Experiment {
  id: number
  hypothesis: string
  method: string
  success_criteria: string
  cost: number | null
  started_at: string
  concluded_at: string | null
  outcome: 'proceed' | 'kill' | 'pivot' | null
  learnings: string | null
}

export interface Tranche {
  id: number
  label: string
  amount: number
  milestone: string
  status: 'planned' | 'released'
  released_at: string | null
  released_by: string | null
}

export interface Funding {
  planned: number
  released: number
  tranches: Tranche[]
}

export interface Challenge {
  id: string
  title: string
  question: string
  theme: string | null
  status: 'active' | 'closed'
  created_at: string
  closes_at: string | null
  ideas_count: number
}

export interface Initiative {
  id: string
  name: string
  objective: string
  created_at: string
  ideas_count: number
  cases_count: number
  estimated_idea_benefit: number
  forecast_annual_savings: number
  verified_annual_savings: number
}

export interface DemoStatus {
  client: string
  industry: string
  generated_by: string
  initiatives: number
  ideas: number
  generated_at: string
}

export interface Notification {
  id: number
  subject_type: string
  subject_id: string
  message: string
  created_at: string
}

export interface Pattern {
  case_id: string
  title: string
  category: string | null
  horizon: string | null
  forecast_annual_savings: number | null
  measured_annual_savings: number | null
  summary: string
  stage: Stage
  story: {
    problem: string
    what_we_tried: { hypothesis: string; outcome: string | null; learnings: string | null }[]
    human_evidence: { kpi: string; value: number; date: string }[]
    credited_to: string | null
  }
}

export interface ScoringConfig {
  idea_weights: Record<string, number>
  priority_themes: string[]
  guardrails: {
    min_annual_benefit: number
    require_category: boolean
    require_benefit_estimate: boolean
  }
  opportunity_weights: { value: number; efficiency: number; speed: number; simplicity: number }
}

export interface WorkflowEvent {
  created_at: string
  subject_type: string
  subject_id: string
  action: string
  actor: string | null
  comment: string | null
}

export interface GateCheck {
  check: string
  passed: boolean
}

export interface QueuedIdea extends Idea {
  gate_checklist: GateCheck[]
}

export interface LifecycleStage {
  stage: string
  step: string
  gate: string
  forum: string
  purpose: string
  criteria: string[]
  decisions: string[]
}

export interface Lifecycle {
  spec: LifecycleStage[]
  idea_counts: Record<string, number>
  idea_terminal: { backlog: number; declined: number }
  case_counts: Record<string, number>
  register: {
    id: string
    title: string
    status: string
    impact: number
    readiness: number
    score: number
    votes: number
  }[]
}

export interface CommandQueue {
  idea_queues: {
    screening: QueuedIdea[]
    prioritization: QueuedIdea[]
    development: QueuedIdea[]
    backlog: Idea[]
  }
  cases_pending_approval: BusinessCase[]
  cases_in_experiment: BusinessCase[]
  cases_in_motion: BusinessCase[]
  history: WorkflowEvent[]
  governance: Record<string, string[]>
}

export interface HubMetrics {
  pipeline_stages: Record<Stage, number>
  time_to_value: {
    median_days_to_live: number | null
    median_days_live_to_evidence: number | null
  }
  ideas: { total: number; by_status: Record<string, number>; conversion_rate: number | null }
  experiments: {
    running: number
    concluded: number
    by_outcome: Record<string, number>
    kill_rate: number | null
  }
  horizon_mix: Record<string, { count: number; value: number; share: number | null; target_share: number | null }>
  automation: {
    last_run: string | null
    actions_by_rule: Record<string, number>
    recent: { run_at: string; rule: string; action: string; subject: string | null; detail: string }[]
  }
}

export interface DashboardData {
  headline: string
  decisions: Decision[]
  portfolio_health: number | null
  hub: HubMetrics
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
  generated_by: 'claude' | 'template' | 'automation'
  note: string | null
  linked_opportunity: LinkedOpportunity | null
  status: 'proposed' | 'implemented'
  stage: Stage
  horizon: string
  initiative_id: string | null
  experiments: Experiment[]
  funding: Funding
  stage_history: { stage: Stage; entered_at: string }[]
  go_live_date: string | null
  kpi_readings: KpiReading[]
  savings_entries: SavingsEntry[]
  metric_bindings: MetricBinding[]
  tracking: Tracking | null
}

export interface PipelineStageBlock {
  stage: string
  count: number
  value: number
  verified: number
  items: { id: string; title: string; value: number; verified?: number; days_in_stage: number | null; owner: string | null }[]
  reached: number
  conversion_from_previous: number | null
  median_dwell_days: number | null
  aging: number
}

export interface PipelineData {
  phases: { phase: string; kind: 'idea' | 'case'; stages: PipelineStageBlock[] }[]
  aging_threshold_days: number
  terminal: { backlog: number; declined: number; closed: number }
  totals: {
    in_flight: number
    pipeline_value: number
    verified_value: number
    end_to_end_conversion: number | null
  }
}
