export type Role = 'CHW_PHC_WORKER' | 'HEALTH_OFFICER' | 'ADMIN'

export type TriageLevel = 'ROUTINE' | 'CONCERNING' | 'URGENT'
export type SafetyVerdict = 'PASS' | 'DOWNGRADE' | 'BLOCK'
export type Severity = 'LOW' | 'MODERATE' | 'HIGH'
export type AlertStatus = 'DETECTED' | 'UNDER_INVESTIGATION' | 'CLOSED'
export type Outcome = 'VALID_SIGNAL' | 'FALSE_ALERT' | 'RESOLVED'

/** A village's researched real-world community profile — present only for
 *  a village that actually has one (currently Manikkampatti / Village B);
 *  `null` for every other village, including Village A. Every field is
 *  either a verified researched value or the literal string "Not
 *  reported" (see `healthcare_access`) — never inferred or guessed. */
export interface VillageRealWorldProfile {
  village_name: string
  taluk: string
  district: string
  state: string
  pin_code: string
  census_village_code: string
  population: number | null
  households: number | null
  male_population: number | null
  female_population: number | null
  children_0_6: number | null
  area_hectares: string | null
  demographic_baseline_year: number | null
  healthcare_access: {
    asha_chw: string
    nearby_government_phc: string
    health_sub_centre: string
    phc_inside_village: string
    chc_inside_village: string
  }
}

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
  village_profile: VillageRealWorldProfile | null
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
  /** Patient details — persist on the patient record across every
   *  assessment, never per-encounter. Blank/null where never recorded. */
  height_cm: number | null
  weight_kg: number | null
  phone_number: string
  house_location: string
  village: number
  village_name: string
  village_code: string
  assessment_count: number
  created_at: string
}

export type BloodSugarMeasurementType = 'fasting' | 'random' | '2_hour_post_meal'

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
  pulse_bpm: number | null
  respiratory_rate: number | null
  systolic_bp: number | null
  diastolic_bp: number | null
  spo2: number | null
  /** Blood glucose reading in mg/dL — null on assessments recorded before
   *  this field existed, or where the worker had no reading available. */
  sugar_mg_dl: number | null
  /** Context for `sugar_mg_dl` — '' when there is no sugar reading, and
   *  '' (not inferred) on an older assessment that has a reading but was
   *  recorded before this field existed. */
  blood_sugar_measurement_type: BloodSugarMeasurementType | ''
  notes: string
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
  village: {
    code: string
    name: string
    cluster: string
    real_world_profile: VillageRealWorldProfile | null
  } | null
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

export type RelationshipKind = 'AGREE' | 'DISAGREE' | 'NOT_COMPARABLE'

export interface EvidenceRelationshipEdge {
  source_a: string
  source_a_kind: string
  what_a_reported: string
  source_b: string
  source_b_kind: string
  what_b_reported: string
  relationship: RelationshipKind
  relationship_label: string
  statement: string
  reason: string
  investigate: string | null
}

export interface EvidenceRelationshipContext {
  source_kind: string
  source_kind_display: string
  source_name: string
  status: string
  status_display: string
  relationship: RelationshipKind
  relationship_label: string
  reason: string
}

export interface EvidenceRelationships {
  anchor: { source_kind: string; source_kind_display: string } | null
  edges: EvidenceRelationshipEdge[]
  context: EvidenceRelationshipContext[]
  summary: {
    agree_count: number
    disagree_count: number
    not_comparable_count: number
    has_disagreement: boolean
  }
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
  relationships: EvidenceRelationships
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
    real_world_profile: VillageRealWorldProfile | null
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
  new_local_signal_reports: number
  recent_local_signal_reports: LocalSignalReport[]
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

/** A worker's "Report to Health Officer" flag on one above-baseline local
 *  signal — see backend `community.models.LocalSignalReport`. Separate from
 *  `OfficerCommunityReport` (a worker's whole-week submission). */
export interface LocalSignalReport {
  id: number
  village_name: string
  village_code: string
  worker_name: string
  category: string
  label: string
  source_kind: string
  source_label: string
  week_label: string
  baseline: number | null
  value: number | null
  unit: string
  change_pct: number | null
  note: string
  created_at: string
  acknowledged: boolean
}

export interface VillageRef {
  code: string
  label: string
  name: string
  cluster: string
  real_world_profile: VillageRealWorldProfile | null
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
    real_world_profile: VillageRealWorldProfile | null
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

// --- GramSentinel Intelligence Simulator (Phase 2 — read-only) -------------

export type SimulationScenarioType =
  | 'EMERGING_SIGNAL'
  | 'STABLE_COMMUNITY'
  | 'WEAK_EVIDENCE'
  | 'MISSING_DATA'
  | 'SOURCE_DISAGREEMENT'
  | 'WHAT_IF'
  | 'REPLAY'
  | 'LIVE_EMERGENCE'

/** GET /api/simulation/scenarios/ row shape. Selecting a scenario in Phase 2
 *  only highlights a card and shows this description — it never starts a
 *  session, calls an agent, or touches operational data. */
export interface SimulationScenario {
  id: number
  name: string
  scenario_type: SimulationScenarioType
  scenario_type_display: string
  description: string
  village_code: string
  village_name: string
  is_active: boolean
  version: number
}

/** One source's synthetic value (or absence) for one simulated week —
 *  mirrors the backend's SimulationSourceSignal exactly, including the
 *  "reported=false means no report, never a silent 0" distinction. */
export interface SimulationSourceValue {
  source_type: string
  reported: boolean
  value: number | null
}

/** The response shape of both POST /simulation/sessions/ (start) and
 *  POST /simulation/sessions/<id>/advance/ — the backend is the sole
 *  authority for week/values/status; nothing here is ever computed or
 *  incremented on the frontend (Phase 3 task §10/§11/§18). */
export interface SimulationSessionState {
  session_id: number
  scenario_id: number
  scenario_name: string
  village_code: string
  village_name: string
  /** Session lifecycle — the real Phase 2 values: NOT_STARTED / IN_PROGRESS / COMPLETED. */
  status: string
  status_display: string
  week: number
  total_weeks: number
  values: {
    categories: Record<string, number>
    status_label: string
    sources: SimulationSourceValue[]
  }
  is_complete: boolean
  /** Phase 4 — one row per pipeline stage for the week just advanced to.
   *  Empty on the response from `start()` (week 1 has no "previous week" to
   *  analyse yet); exactly 5 entries, in fixed pipeline order, on every
   *  `advance()` response. */
  agent_runs: SimulationAgentRun[]
}

// --- GramSentinel Intelligence Simulator (Phase 5 — Signal Intelligence) ---

/** One reporting week's actual synthetic value for the session's primary
 *  signal — `value` is `null` only when that week's category total is
 *  genuinely absent from the backend record, never a stand-in for 0
 *  (task §4/§5). `status` is that week's own deterministic trend
 *  classification (Phase 4's `signal_analysis` output, or `NORMAL` for
 *  week 1, which has no prior week to compare against). */
export interface SimulationTimelinePoint {
  week: number
  primary_signal: string | null
  value: number | null
  status: string
  sources: SimulationSourceValue[]
}

/** SUPPORTING / CONFLICTING / INSUFFICIENT — Phase 4's own frozen
 *  correlation vocabulary (kept as-is rather than the task's illustrative
 *  "SUPPORTS"/"CONFLICTS" spelling, so the Agent Pipeline view above and
 *  the Intelligence View below never show two different words for the
 *  same underlying relationship). */
export type SimulationRelation = 'SUPPORTING' | 'CONFLICTING' | 'INSUFFICIENT'

export interface SimulationConstellationEntry {
  source: string
  relation: SimulationRelation
  reason: string
}

export interface SimulationSourceFusionEntry extends SimulationConstellationEntry {
  reported: boolean | null
  current_value: number | null
}

export interface SimulationDataQualitySource {
  source: string
  reported_weeks: number
  expected_weeks: number
  completeness_pct: number
}

/** `completeness_pct` = reported_weeks / expected_weeks, both overall and
 *  per source (task §10) — never an invented confidence figure. `missing`
 *  lists every `source — Week N` that was not reported, explicitly, rather
 *  than only implying it through a lower percentage. */
export interface SimulationDataQuality {
  expected_weeks: number
  window_label: string
  completeness_pct: number
  missing: string[]
  sources: SimulationDataQualitySource[]
  duplicates_checked: boolean
}

/** Evidence Strength is WEAK / MODERATE / STRONG — a fixed deterministic
 *  category, never a percentage or "confidence" figure (task §16/§17).
 *  `safety_status` is always a truthful statement sourced directly from
 *  the Phase 6 Safety Engine's own safety-stage output — never
 *  "passed"/"failed"/"approved" wording invented on the frontend. */
export interface SimulationExplanation {
  signal: string
  sources_supporting: string[]
  sources_conflicting: string[]
  sources_insufficient: string[]
  reporting_periods: string
  data_quality_summary: string
  evidence_strength: 'WEAK' | 'MODERATE' | 'STRONG'
  routed_reason: string
  suggested_verification: string
  safety_status: string
}

// --- GramSentinel Intelligence Simulator (Phase 6 — Safety Engine) ---------

export type SimulationSafetyGateResult = 'PASS' | 'BLOCK' | 'INSUFFICIENT'

/** One of the Safety Engine's nine fixed-order deterministic rule results
 *  (task §5/§6/§7) — `rule` is a stable snake_case name, never reordered,
 *  never frontend-selected. */
export interface SimulationSafetyCheckEntry {
  rule: string
  result: SimulationSafetyGateResult
  reason: string
}

/** `GET /simulation/sessions/<id>/safety/`'s exact shape, and exactly what
 *  the embedded `intelligence.safety` key also carries (task §19) — the
 *  same computation either way, never two answers for one session.
 *  `gate_result` is BLOCK > INSUFFICIENT > PASS over the nine checks
 *  above; `human_review_required` is always `true` (task §9);
 *  `evidence_strength` is Phase 5's preliminary WEAK/MODERATE/STRONG,
 *  downgraded-only by safety, never upgraded. All three come from the
 *  backend — the frontend never computes any of them (task §21).
 *
 *  `gate_result`/`evidence_strength` are `null`, `checks` is empty, and
 *  `not_evaluated_reason` is set only for a Phase 7 Replay week that has
 *  no persisted safety result yet (week 1, or a week whose pipeline
 *  failed) — a truthful "not evaluated" state, never a fabricated PASS. */
export interface SimulationSafetyResult {
  checks: SimulationSafetyCheckEntry[]
  gate_result: SimulationSafetyGateResult | null
  human_review_required: boolean
  evidence_strength: 'WEAK' | 'MODERATE' | 'STRONG' | null
  not_evaluated_reason?: string
}

/** The one shared object every Intelligence View component reads from —
 *  `GET /simulation/sessions/<id>/intelligence/`'s exact response shape.
 *  Frozen per the Phase 5 task (§2/§43): Phase 6 adds a sixth `safety` key
 *  alongside these five, never restructures them. */
export interface SimulationIntelligence {
  timeline: SimulationTimelinePoint[]
  constellation: SimulationConstellationEntry[]
  source_fusion: SimulationSourceFusionEntry[]
  data_quality: SimulationDataQuality
  explanation: SimulationExplanation
  safety: SimulationSafetyResult
  /** The exact same Phase 9/10 `suggested_decision()` the Investigation
   *  Notebook already computes, reused here — never a second
   *  recommendation algorithm. `''` while Safety is BLOCK (nothing to
   *  suggest) — see `backend/simulation/investigation.py`. */
  suggested_next_step: InvestigationDecisionValue | ''
}

// --- GramSentinel Intelligence Simulator (Phase 7 — Replay) ----------------

/** `GET /simulation/sessions/<id>/replay/?week=N`'s exact shape — a pure,
 *  read-only re-display of an already-computed week (task §7: "replay
 *  does not recompute persisted agent or safety results"). `week` is
 *  `null` only in the defensive case where nothing has ever been
 *  revealed for this session. */
export interface SimulationReplayState {
  week: number | null
  min_week: number
  max_week: number
  is_first: boolean
  is_last: boolean
  intelligence: SimulationIntelligence
}

export type SimulationReplaySpeed = 0.5 | 1 | 2 | 5

// --- GramSentinel Intelligence Simulator (Phase 7 — What-If) ---------------

export interface SimulationWhatIfSourceValue {
  value: number | null
  reported: boolean
}

/** One stage's raw output from the real Phase 4 pipeline, rerun against
 *  hypothetical inputs — shown for transparency (the same "view raw
 *  input/output" idea the live Agent Pipeline card already offers), never
 *  as a second source of truth for the summary fields above it. */
export interface SimulationWhatIfPipelineStage {
  agent: SimulationAgentName
  status: string
  output: Record<string, unknown>
}

export interface SimulationWhatIfOriginal {
  sources: Record<string, SimulationWhatIfSourceValue>
  /** Added for Counterfactual Investigation's Original-vs-Hypothetical
   *  comparison — derived the same way Replay already reads an
   *  already-computed week (`build_intelligence(as_of_week=...)`), never a
   *  second computation. */
  trend: string | null
  constellation: SimulationConstellationEntry[]
  supporting_count: number
  conflicting_count: number
  missing_count: number
  gate_result: SimulationSafetyGateResult | null
  evidence_strength: 'WEAK' | 'MODERATE' | 'STRONG' | null
  human_review_required: boolean
}

export interface SimulationWhatIfHypothetical {
  sources: Record<string, SimulationWhatIfSourceValue>
  primary_signal: string | null
  trend: string | null
  constellation: SimulationConstellationEntry[]
  supporting_count: number
  conflicting_count: number
  missing_count: number
  data_quality: SimulationDataQuality
  pipeline: SimulationWhatIfPipelineStage[]
  safety: SimulationSafetyResult
  suggested_next_step: InvestigationDecisionValue | ''
}

/** `POST /simulation/sessions/<id>/what-if/`'s exact response shape — the
 *  backend is authoritative for every value in `hypothetical` (task §35):
 *  the frontend only collects `overrides` and displays this result,
 *  never computes a trend/relationship/evidence-strength/safety verdict
 *  itself. */
export interface SimulationWhatIfResult {
  week: number
  is_hypothetical: true
  original: SimulationWhatIfOriginal
  hypothetical: SimulationWhatIfHypothetical
  changed_sources: string[]
}

// --- GramSentinel Intelligence Simulator (Phase 4 — pipeline execution) ----

/** Canonical stage names, in their permanent, fixed pipeline order. */
export type SimulationAgentName =
  | 'ingestion'
  | 'signal_analysis'
  | 'correlation'
  | 'evidence'
  | 'safety'

export const SIMULATION_STAGE_ORDER: SimulationAgentName[] = [
  'ingestion',
  'signal_analysis',
  'correlation',
  'evidence',
  'safety',
]

/** One `SimulationAgentRun` row exactly as the backend persisted it —
 *  `input`/`output` are opaque structured JSON, deliberately typed loosely
 *  here since each stage's shape differs; the UI reads specific known keys
 *  off `output` defensively rather than assuming a single shared shape. */
export interface SimulationAgentRun {
  agent_name: SimulationAgentName
  /** WAITING (safety stub, or a stage skipped after an earlier failure —
   *  though skipped stages are actually reported as FAILED, see backend
   *  docs) / PROCESSING (never observed in a REST response, execution is
   *  synchronous) / COMPLETE / FAILED. */
  status: 'WAITING' | 'PROCESSING' | 'COMPLETE' | 'FAILED'
  status_display: string
  input: Record<string, unknown>
  output: Record<string, unknown>
  duration_ms: number | null
  started_at: string | null
  ended_at: string | null
}

// --- GramSentinel Intelligence Simulator (Phase 8 — Live Streaming) --------
//
// The event envelope streamed over `WS /ws/simulation/sessions/<id>/`
// (`backend/simulation/consumers.py` + `live_runner.py`). Every event
// carries `type`/`session_id`; the rest of the shape depends on `type`, so
// this is a loosely-typed envelope (like `SimulationAgentRun.output` above)
// rather than a full discriminated union — the store only ever reads the
// few fields each handler actually needs.

export type SimulationLiveEventType =
  | 'simulation.connected'
  | 'simulation.started'
  | 'simulation.week_started'
  | 'simulation.stage'
  | 'simulation.week_completed'
  | 'simulation.completed'
  | 'simulation.paused'
  | 'simulation.resumed'
  | 'simulation.stopped'
  | 'simulation.error'

export interface SimulationLiveEvent {
  type: SimulationLiveEventType
  session_id: number
  village_id?: number
  week?: number | null
  stage?: SimulationAgentName
  status?: 'PROCESSING' | 'COMPLETE' | 'FAILED'
  payload?: SimulationAgentRun
  is_complete?: boolean
  error?: string
  // simulation.connected only — a resync snapshot of already-persisted
  // session state, never a second source of truth for it.
  status_snapshot?: string
  live_running?: boolean
  live_paused?: boolean
}

/** No connection attempted yet / a fresh page load before Live Mode is
 *  entered — distinct from DISCONNECTED, which means a connection existed
 *  and was lost (task's own required connection-state vocabulary). */
export type SimulationLiveStatus =
  | 'IDLE'
  | 'CONNECTING'
  | 'CONNECTED'
  | 'DISCONNECTED'
  | 'RECONNECTING'
  | 'ERROR'

export type SimulationLiveStageStatus = 'WAITING' | 'PROCESSING' | 'COMPLETE' | 'FAILED'

// --- GramSentinel Intelligence Simulator (Phase 9 — Investigation Notebook)

export type InvestigationStatus =
  | 'NOT_STARTED'
  | 'IN_PROGRESS'
  | 'READY_FOR_DECISION'
  | 'DECISION_RECORDED'
  | 'COMPLETED'

/** A next investigative STEP, never a medical/treatment recommendation —
 *  see `backend/simulation/models.py::InvestigationDecision`'s own
 *  docstring for why this is its own vocabulary, not a reuse of the
 *  operational `Feedback.Outcome`. */
export type InvestigationDecisionValue =
  | 'CONTINUE_MONITORING'
  | 'REQUEST_MORE_DATA'
  | 'VERIFY_WITH_PHC'
  | 'CONDUCT_FIELD_VERIFICATION'
  | 'REQUEST_LABORATORY_VERIFICATION'
  | 'ESCALATE_FOR_HUMAN_REVIEW'
  | 'CLOSE_AS_INSUFFICIENT_EVIDENCE'

export const INVESTIGATION_DECISION_LABELS: Record<InvestigationDecisionValue, string> = {
  CONTINUE_MONITORING: 'Continue Monitoring',
  REQUEST_MORE_DATA: 'Request More Data',
  VERIFY_WITH_PHC: 'Verify with PHC',
  CONDUCT_FIELD_VERIFICATION: 'Conduct Field Verification',
  REQUEST_LABORATORY_VERIFICATION: 'Request Laboratory Verification',
  ESCALATE_FOR_HUMAN_REVIEW: 'Escalate for Human Review',
  CLOSE_AS_INSUFFICIENT_EVIDENCE: 'Close as Insufficient Evidence',
}

export interface InvestigationOverview {
  investigation_id: number
  session_id: number
  village_code: string
  village_name: string
  scenario_name: string
  week: number
  total_weeks: number
  status: InvestigationStatus
  status_display: string
  primary_signal: string | null
  trend: string | null
  evidence_strength: 'WEAK' | 'MODERATE' | 'STRONG' | null
  investigation_priority: string
  safety_gate_result: SimulationSafetyGateResult | null
  sources_supporting: string[]
  sources_conflicting: string[]
  sources_insufficient: string[]
  why_am_i_seeing_this: string | null
}

export interface InvestigationChecklistItem {
  key: string
  label: string
}

export interface InvestigationChecklistProgress {
  checked: number
  total: number
  percent: number
}

export interface InvestigationContradiction {
  source: string
  relation: SimulationRelation
  reason: string
  current_value: number | null
  reported: boolean | null
  suggested_verification: string[]
}

export interface InvestigationCommunityContextEntry {
  week: number
  note: string
}

export interface InvestigationObservation {
  id: number
  week: number
  source: string
  category: string
  notes: string
  created_at: string
}

export interface InvestigationDecisionState {
  value: InvestigationDecisionValue | ''
  value_display: string
  reason: string
  decided_by: string | null
  decided_at: string | null
}

export interface InvestigationActivityEntry {
  timestamp: string
  event_type: string
  actor: string
}

/** The one `GET/PATCH .../investigation/` payload shape — everything the
 *  Investigation Notebook reads, deliberately NOT re-embedding the
 *  existing `SimulationIntelligence`/safety payloads (those are fetched
 *  separately, via the existing store fields — task's own "do not
 *  duplicate the intelligence payload" rule). */
export interface SimulationInvestigationState {
  overview: InvestigationOverview
  checklist: {
    items: InvestigationChecklistItem[]
    values: Record<string, boolean>
    progress: InvestigationChecklistProgress
  }
  contradictions: InvestigationContradiction[]
  community_context: InvestigationCommunityContextEntry[]
  observations: InvestigationObservation[]
  notes: string
  decision: InvestigationDecisionState
  suggested_decision: InvestigationDecisionValue | ''
  activity_history: InvestigationActivityEntry[]
  status: InvestigationStatus
  status_display: string
}

// --- GramSentinel Intelligence Simulator (Phase 10 — Feedback)

/** Describes the OFFICER'S EXPERIENCE, never ground truth (task §6) —
 *  "Officer assessment", not "the signal was correct". */
export type FeedbackUsefulness = 'VERY_USEFUL' | 'USEFUL' | 'PARTIALLY_USEFUL' | 'NOT_USEFUL'
export type FeedbackEvidenceSufficiency = 'SUFFICIENT' | 'PARTIALLY_SUFFICIENT' | 'INSUFFICIENT'
export type FeedbackYesPartiallyNo = 'YES' | 'PARTIALLY' | 'NO'
export type FeedbackYesNo = 'YES' | 'NO'

export const FEEDBACK_USEFULNESS_LABELS: Record<FeedbackUsefulness, string> = {
  VERY_USEFUL: 'Very Useful',
  USEFUL: 'Useful',
  PARTIALLY_USEFUL: 'Partially Useful',
  NOT_USEFUL: 'Not Useful',
}

export const FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS: Record<FeedbackEvidenceSufficiency, string> = {
  SUFFICIENT: 'Sufficient',
  PARTIALLY_SUFFICIENT: 'Partially Sufficient',
  INSUFFICIENT: 'Insufficient',
}

export const FEEDBACK_YES_PARTIALLY_NO_LABELS: Record<FeedbackYesPartiallyNo, string> = {
  YES: 'Yes',
  PARTIALLY: 'Partially',
  NO: 'No',
}

export const FEEDBACK_YES_NO_LABELS: Record<FeedbackYesNo, string> = { YES: 'Yes', NO: 'No' }

/** The one `GET/PATCH .../investigation/feedback/` payload shape.
 *  `submitted: false` is structurally distinct from any real choice —
 *  "missing" is never coerced into "not useful" (task §23). */
export interface SimulationFeedbackState {
  submitted: boolean
  usefulness: FeedbackUsefulness | ''
  evidence_sufficiency: FeedbackEvidenceSufficiency | ''
  recommendation_helpful: FeedbackYesPartiallyNo | ''
  additional_verification_required: FeedbackYesNo | ''
  comment: string
  officer: string | null
  updated_at: string | null
}
