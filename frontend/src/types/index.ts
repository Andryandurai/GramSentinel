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

/** One optional day of recorded symptom history. */
export interface SymptomDay {
  day: number
  detail: string
}

/**
 * The optional free-text detail a worker added. Carried through the agent
 * chain for display and storage only — it is never scored, and never reaches
 * the deterministic safety checks.
 */
export interface SupplementaryContext {
  other_symptom_text: string
  symptom_timeline: SymptomDay[]
  has_supplementary_detail: boolean
  interpreted_by_triage: boolean
  note: string
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
  /** Absent on responses produced before this field existed. */
  supplementary_context?: SupplementaryContext
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
  /** Empty when the worker did not record an "Other" symptom. */
  other_symptom_text: string
  duration_days: number
  /** Empty when day-wise details were not recorded. Old records have none. */
  symptom_timeline: SymptomDay[]
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

export type FollowUpState =
  | 'OVERDUE'
  | 'DUE_TODAY'
  | 'UPCOMING'
  | 'COMPLETED'
  | 'MISSED'
  | 'UNSCHEDULED'

export interface FollowUp {
  id: number
  patient: number
  patient_code: string
  patient_name: string
  assessment: number | null
  due_date: string
  status: 'PENDING' | 'COMPLETED' | 'MISSED'
  /** Derived from the stored due date — what the card sorts and labels by. */
  followup_status: FollowUpState
  followup_status_label: string
  days_until_due: number | null
  due_description: string
  notes: string
  created_at?: string
}

export interface FollowUpPatientOption {
  id: number
  patient_code: string
  patient_name: string
  pending_count: number
  next_due_date: string | null
  next_status: FollowUpState
}

export interface FollowUpSummary {
  counts: {
    total: number
    shown: number
    overdue: number
    due_today: number
    upcoming: number
    undated: number
  }
  patients: FollowUpPatientOption[]
  overdue_outside_period: number
  overdue_outside_message: string
  empty_message: string
  truncated: boolean
  truncated_message: string
}

/** One row of the Community Symptom Summary — reported symptoms, not cases. */
export interface SymptomSummaryRow {
  key: string
  label: string
  count: number
  report_category: string | null
  hint: string
}

export interface SymptomSummary {
  rows: SymptomSummaryRow[]
  total_people_assessed: number
  assessment_count: number
  described_other_count: number
  is_empty: boolean
  empty_message: string
  note: string
  report_prefill: Array<{ category: string; case_count: number; label: string }>
  period_label: string
  is_all_weeks: boolean
  village_name: string
}

/** One selectable reporting week, numbered across the data the worker can see. */
export interface DashboardWeek {
  value: string
  number: number
  label: string
  start: string
  end: string
  range_label: string
  is_current_week: boolean
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
  weeks: DashboardWeek[]
  selected_week: string
  period: {
    is_all_weeks: boolean
    label: string
    range_label: string
    start: string | null
    end: string | null
    assessment_count: number
    urgent_count: number
    concerning_count: number
    followup_count: number
    has_activity: boolean
    empty_message: string
    notice: string
  }
  pending_followups: FollowUp[]
  pending_followup_count: number
  followup_summary: FollowUpSummary
  symptom_summary: SymptomSummary
  recent_assessments: Assessment[]
  disclaimer: string
  data_notice: string
}

/** A worker's or officer's professional profile. */
export interface StaffProfile {
  id: number
  username: string
  role: Role
  role_label: string
  display_name: string
  full_name: string
  email: string
  phone_number: string
  staff_id: string
  qualification: string
  experience_years: number | null
  district: string
  village: number | null
  village_name: string | null
  village_code: string | null
  village_cluster: string | null
  village_label: string
  facility: number | null
  facility_name: string | null
  photo_url: string
  has_photo: boolean
  initials: string
  profile_updated_at: string | null
}

export interface MyProfileResponse {
  profile: StaffProfile
  photo_limits: {
    max_bytes: number
    max_size_label: string
    accepted_label: string
    accepted_types: string[]
  }
  note: string
  editable_fields: string[]
  saved?: boolean
  message?: string
}

export interface StaffDirectory {
  scope: {
    is_district_wide: boolean
    village_code: string | null
    village_name: string | null
    notice: string
  }
  villages: Array<{ code: string; name: string; label: string; cluster: string }>
  profiles: StaffProfile[]
  groups: Array<{
    village_code: string
    village_name: string
    village_label: string
    workers: StaffProfile[]
    officers: StaffProfile[]
  }>
  counts: { workers: number; officers: number; total: number }
  is_empty: boolean
  empty_message: string
  note: string
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
  /** Actual worker-reported signal counts over time — see CommunitySeries. */
  community_trend: CommunitySeries
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
  /** Each person carries their professional profile alongside the assignment. */
  team: Array<
    VillageRef & {
      workers: Array<{ username: string; name: string } & Partial<StaffProfile>>
      officers: Array<{ username: string; name: string } & Partial<StaffProfile>>
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

/**
 * Weekly, per-category counts of ACTUAL reported cases from
 * `CommunityReportEntry` (what Health Workers submitted through the
 * Community Report form) — real integers, never a percentage of a baseline.
 * Shared by the Officer Dashboard's chart and the Community Data page's
 * chart so both read from the same underlying series shape.
 */
export interface CommunitySeries {
  keys: string[]
  points: Array<Record<string, string | number>>
  /** Reflects the selected filters, e.g. "Reported high-severity …". */
  title: string
  total_reported: number
  weeks_covered: number
  trend: {
    current: number
    previous: number | null
    change_pct: number | null
    direction: TrendDirection
    direction_label: string
    symbol: string
    is_new_activity: boolean
  }
  trend_note: string
  is_empty: boolean
  empty_message: string
  empty_hint: string
  applied: { severity: string; category: string }
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
  series: CommunitySeries
  filters: {
    severity: {
      selected: string
      options: Array<{ value: string; label: string; alerts: number }>
    }
    category: {
      selected: string
      options: Array<{
        value: string
        label: string
        reported: number
        has_data: boolean
      }>
    }
    notice: string
    note: string
  }
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
