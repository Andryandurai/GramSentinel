export type Role = 'CHW_PHC_WORKER' | 'HEALTH_OFFICER' | 'PATIENT' | 'ADMIN'

export type TriageLevel = 'ROUTINE' | 'CONCERNING' | 'URGENT'
export type SafetyVerdict = 'PASS' | 'DOWNGRADE' | 'BLOCK'
export type Severity = 'LOW' | 'MODERATE' | 'HIGH'
export type AlertStatus = 'DETECTED' | 'UNDER_INVESTIGATION' | 'CLOSED'
export type Outcome = 'VALID_SIGNAL' | 'FALSE_ALERT' | 'RESOLVED'

export interface User {
  id: number
  username: string
  role: Role
  display_name: string
  full_name: string
  district: string
  village: number | null
  village_name: string | null
  village_code: string | null
  village_cluster: string | null
  facility_name: string | null
}

export interface RedFlag {
  code: string
  label: string
  rationale: string
}

export interface SafetyRule {
  code: string
  name: string
  passed: boolean
  severity: 'BLOCKING' | 'DOWNGRADING' | 'ADVISORY'
  detail: string
}

export interface SafetyResult {
  verdict: SafetyVerdict
  passed: boolean
  status: string
  rules_checked: SafetyRule[]
  reasons: string[]
  severity: string | null
  confidence: number
  corroborating_source_count: number
  engine_version: string
  requires_human_review: boolean
}

export interface AgentTraceEntry {
  sequence: number
  stage: string
  agent: string
  /** Plain-language name, purpose and result produced by the agent itself. */
  display_name: string
  purpose: string
  result_summary: string
  layer: string
  status: string
  duration_ms: number
  used_llm: boolean
  input_summary: Record<string, unknown>
  output: Record<string, unknown>
}

export interface TriageSupport {
  triage_level: TriageLevel
  model_triage_level: TriageLevel
  triage_score: number
  contributing_factors: string[]
  reasoning_summary: string
  referral_recommendation: string
  referral_pathway: string
  followup_interval_days: number | null
  red_flags: RedFlag[]
  escalation_forced: boolean
  safety_status: string
  safety_note: string
  safety_result: SafetyResult
  normalised_symptoms: string[]
  syndrome_groups: Record<string, string[]>
  completeness: { notes: string[]; is_complete: boolean; missing_vitals: string[] }
  signal_category: string
  llm_used: boolean
  agent_trace: AgentTraceEntry[]
  flow: string[]
  disclaimer: string
  data_notice: string
}

export interface Patient {
  id: number
  patient_code: string
  display_name: string
  age_years: number | null
  age_months: number | null
  sex: string
  village: number
  village_name: string
  village_code: string
  assessment_count: number
  created_at: string
}

export interface Assessment {
  id: number
  patient: number
  patient_code: string
  patient_name: string
  village_name: string
  worker_name: string
  symptoms: string[]
  duration_days: number
  temperature_c: number | null
  primary_category: string
  triage_level: TriageLevel
  triage_score: number
  reasoning_summary: string
  referral_recommendation: string
  red_flags: RedFlag[]
  escalation_forced: boolean
  safety_status: string
  encounter_date: string
  aggregated_at: string | null
  created_at: string
}

export interface FollowUp {
  id: number
  patient: number
  patient_code: string
  patient_name: string
  due_date: string
  status: 'PENDING' | 'COMPLETED' | 'MISSED'
  notes: string
}

export interface WorkerDashboard {
  worker: string
  village: { code: string; name: string; cluster: string } | null
  today: {
    date: string
    assessment_count: number
    urgent_count: number
    concerning_count: number
  }
  pending_followups: FollowUp[]
  pending_followup_count: number
  recent_assessments: Assessment[]
  disclaimer: string
  data_notice: string
}

export interface AlertSummary {
  id: number
  alert_uid: string
  title: string
  cluster: string
  village_name: string
  village_code: string
  category: string
  week_label: string
  period_start: string
  period_end: string
  severity: Severity
  confidence: number
  corroborating_source_count: number
  cross_level_verdict: string
  safety_verdict: SafetyVerdict
  safety_status: string
  status: AlertStatus
  outcome: Outcome | null
  created_at: string
}

export interface EvidenceCard {
  id: number
  source_kind: string
  source_kind_display: string
  source_name: string
  category: string
  village_code: string
  week_label: string
  baseline: number | null
  current_value: number | null
  change_pct: number | null
  unit: string
  data_quality: string
  status: string
  status_display: string
  is_corroborating: boolean
  explanation: string
  produced_by_agent: string
}

export interface AlertEvidenceResponse {
  alert: {
    id: number
    alert_uid: string
    title: string
    summary: string
    cluster: string
    village: string
    category: string
    week_label: string
    period_start: string
    period_end: string
    severity: Severity
    confidence: number
    status: AlertStatus
    narrative_used_llm: boolean
  }
  why_this_alert: {
    corroborating_sources: string[]
    corroborating_count: number
    context_sources: string[]
    not_reported_sources: string[]
    explanation: string
  }
  evidence: EvidenceCard[]
  cross_level: { verdict: string; statement: string }
  safety_check: {
    verdict: SafetyVerdict
    passed: boolean
    status: string
    rules: SafetyRule[]
    reasons: string[]
    engine_version: string
  } | null
  agent_trace: AgentTraceEntry[]
  flow: string[]
  human_review: { required: boolean; note: string }
  data_notice: string
}

export interface TrendPoint {
  week_label: string
  value: number
  baseline: number | null
  category: string
  village: string
}

export interface OfficerDashboard {
  officer: string
  district: string
  scope: {
    village_code: string | null
    village_name: string | null
    is_district_wide: boolean
  }
  new_reports: number
  recent_reports: Array<{
    id: number
    village_name: string
    worker_name: string
    week_label: string
    submitted_at: string
    unusual_observation: boolean
    acknowledged: boolean
    total_cases: number
    categories: Array<{
      category: string
      label: string
      case_count: number
      description: string
    }>
  }>
  summary: {
    active_alerts: number
    under_investigation: number
    closed_alerts: number
    high_severity: number
    safety_passed: number
    safety_downgraded: number
    villages_monitored: number
    mean_confidence: number
    human_review_rate: number
  }
  outcomes: { valid_signal: number; false_alert: number; resolved: number }
  alerts: AlertSummary[]
  trends: Record<string, TrendPoint[]>
  disclaimer: string
  data_notice: string
}

export interface PatientPortal {
  patient: {
    patient_code: string
    display_name: string
    age_years: number | null
    village_name: string
  }
  records: Array<{
    id: number
    encounter_date: string
    symptoms: string[]
    duration_days: number
    triage_level: TriageLevel
    referral_recommendation: string
    followup_interval_days: number | null
  }>
  followups: Array<{
    id: number
    due_date: string
    status: string
    notes: string
  }>
  guidance: string[]
  scope_note: string
  disclaimer: string
}

export interface LocalSignalRow {
  id: number
  source_kind: string
  source_name: string
  category: string
  week_label: string
  value: number | null
  baseline: number | null
  unit: string
  change_pct: number | null
  is_reported: boolean
  data_quality: string
}

export interface LocalSignalGroup {
  category: string
  label: string
  is_rising: boolean
  signals: LocalSignalRow[]
}

export interface LocalSignals {
  village: { code: string; name: string; cluster: string } | null
  headline: string
  rising_categories: string[]
  signals: LocalSignalRow[]
  grouped: LocalSignalGroup[]
  scope_note: string
  signal_note: string
}

export interface VillageRef {
  code: string
  label: string
  name: string
  cluster: string
}

export interface AdminOverview {
  scope: {
    mode: 'all' | 'village'
    village: VillageRef | null
    label: string
    village_count: number
  }
  villages: VillageRef[]
  totals: {
    patients: number
    assessments: number
    urgent_assessments: number
    community_reports: number
    reported_cases: number
    signals: number
    workers: number
    officers: number
    alerts_total: number
    alerts_active: number
    alerts_under_investigation: number
    alerts_resolved: number
    alerts_high_severity: number
    investigations: number
    outcome_valid_signal: number
    outcome_false_alert: number
    outcome_resolved: number
  }
  village_summary: Array<
    VillageRef & {
      patients: number
      assessments: number
      community_reports: number
      active_alerts: number
      under_investigation: number
      resolved_alerts: number
      workers: number
      officers: number
      status: string
    }
  >
  signal_categories: Array<{
    category: string
    label: string
    reported_cases: number
    entries: number
    described: number
  }>
  trend: { keys: string[]; points: Array<Record<string, string | number>> }
  alerts: Array<{
    id: number
    title: string
    village_code: string
    village_label: string
    category: string
    category_label: string
    week_label: string
    severity: Severity
    status: AlertStatus
    confidence: number
    safety_verdict: SafetyVerdict
    safety_status: string
    corroborating_source_count: number
    evidence_summary: string
    cross_level_verdict: string
    outcome: Outcome | null
    created_at: string
  }>
  team: Array<
    VillageRef & {
      workers: Array<{ username: string; name: string }>
      officers: Array<{ username: string; name: string }>
    }
  >
  recent_activity: Array<{
    kind: string
    village_code: string
    village_label: string
    summary: string
    at: string
  }>
  is_empty: boolean
  signal_note: string
}

export type TrendDirection =
  | 'INCREASING'
  | 'DECREASING'
  | 'STABLE'
  | 'INSUFFICIENT_DATA'

export interface CommunityDataCategory {
  category: string
  label: string
  described_entries: number
  current: number
  previous: number | null
  change_pct: number | null
  direction: TrendDirection
  direction_label: string
  symbol: string
  is_new_activity: boolean
}

export interface OfficerCommunityData {
  scope: {
    village_code: string | null
    village_name: string | null
    is_district_wide: boolean
  }
  period: {
    days: number
    options: number[]
    current: { start: string; end: string }
    previous: { start: string; end: string }
    has_previous_period_data: boolean
  }
  summary: {
    increasing: number
    decreasing: number
    stable: number
    insufficient_data: number
    categories_reported: number
    total_current_cases: number
    has_previous_period_data: boolean
  }
  categories: CommunityDataCategory[]
  series: { keys: string[]; points: Array<Record<string, string | number>> }
  recent_observations: Array<{
    category: string
    label: string
    case_count: number
    description: string
    village_name: string
    worker_name: string
    week_label: string
    period_start: string
    period_end: string
    unusual_observation: boolean
  }>
  is_empty: boolean
  note: string
  relationship_note: string
}

export interface CommunityReportEntry {
  category: string
  label: string
  case_count: number
  description: string
  notes?: string
}

export interface OfficerCommunityReport {
  id: number
  village_name: string
  village_code: string
  cluster: string
  worker_name: string
  week_label: string
  period_start: string
  period_end: string
  submitted_at: string
  unusual_observation: boolean
  notes: string
  acknowledged: boolean
  total_cases: number
  entries: CommunityReportEntry[]
}
