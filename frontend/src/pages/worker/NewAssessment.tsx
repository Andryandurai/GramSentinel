import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

import { RagGuidancePanel } from '@/components/RagGuidancePanel'
import { TriageSupportPanel } from '@/components/TriageSupport'
import { Card, Empty, ErrorNote, Loading, TriagePill } from '@/components/ui'
import { PregnancyAssessmentFlow } from '@/components/worker/PregnancyAssessmentFlow'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type {
  Assessment,
  BloodSugarMeasurementType,
  Patient,
  RagResponse,
  TriageSupport,
} from '@/types'

/** Machine value -> translation key (under `newAssessment`), reused for both
 *  the entry form's radio group and the Previous Assessments history
 *  display, so the two can never drift. */
const SUGAR_MEASUREMENT_KEYS: Record<BloodSugarMeasurementType, string> = {
  fasting: 'measurementFasting',
  random: 'measurementRandom',
  '2_hour_post_meal': 'measurementPostMeal',
}
const SUGAR_MEASUREMENT_OPTIONS = Object.keys(SUGAR_MEASUREMENT_KEYS) as BloodSugarMeasurementType[]

/** Machine vital-sign field -> translation key (under `newAssessment`), plus
 *  its numeric input step — mirrors the SUGAR_MEASUREMENT_KEYS pattern above
 *  so the label text is never hardcoded in JSX. */
const VITAL_FIELDS: [keyof Pick<
  AssessmentForm,
  'temperature_c' | 'pulse_bpm' | 'respiratory_rate' | 'systolic_bp' | 'diastolic_bp' | 'spo2'
>, string, string][] = [
  ['temperature_c', 'temperature', '0.1'],
  ['pulse_bpm', 'pulse', '1'],
  ['respiratory_rate', 'respiratoryRate', '1'],
  ['systolic_bp', 'systolic', '1'],
  ['diastolic_bp', 'diastolic', '1'],
  ['spo2', 'spo2', '1'],
]

/** Symptom code -> display text, via the `newAssessment.symptomLabels` map.
 *  Falls back to the raw code (underscores replaced with spaces) for any
 *  symptom value not present in the map, so an unexpected backend value
 *  never renders blank. */
function symptomLabel(t: TFunction, code: string): string {
  return t(`newAssessment.symptomLabels.${code}`, {
    defaultValue: code.replace(/_/g, ' '),
  })
}

const SYMPTOM_OPTIONS = [
  'fever',
  'headache',
  'body_pain',
  'chills',
  'cough',
  'sore_throat',
  'breathlessness',
  'chest_pain',
  'diarrhoea',
  'vomiting',
  'abdominal_pain',
  'rash',
  'fatigue',
  'neck_stiffness',
  'altered_consciousness',
  'seizure',
  'bleeding',
]

/** How many optional day-wise boxes the form offers. */
const TIMELINE_DAYS = [1, 2, 3]

type Step = 'choose' | 'new-patient' | 'assessment'

interface AssessmentForm {
  symptoms: string[]
  /** Optional: the worker ticked "Other" and described the symptom. */
  other_selected: boolean
  other_text: string
  duration_days: string
  /** Optional: day-wise history, off unless the worker turns it on. */
  day_wise_enabled: boolean
  day_details: Record<number, string>
  temperature_c: string
  pulse_bpm: string
  respiratory_rate: string
  systolic_bp: string
  diastolic_bp: string
  spo2: string
  sugar_mg_dl: string
  /** '' whenever sugar_mg_dl is '' — the two are cleared together. */
  blood_sugar_measurement_type: BloodSugarMeasurementType | ''
  notes: string
}

const EMPTY_ASSESSMENT: AssessmentForm = {
  symptoms: [],
  other_selected: false,
  other_text: '',
  duration_days: '',
  day_wise_enabled: false,
  day_details: {},
  temperature_c: '',
  pulse_bpm: '',
  respiratory_rate: '',
  systolic_bp: '',
  diastolic_bp: '',
  spo2: '',
  sugar_mg_dl: '',
  blood_sugar_measurement_type: '',
  notes: '',
}

const EMPTY_PATIENT = {
  display_name: '',
  age_years: '',
  age_months: '',
  sex: 'U',
  height_cm: '',
  weight_kg: '',
  phone_number: '',
  house_location: '',
}

/** Patient details — persist on the patient record, editable whenever a
 *  patient (new or existing) is on screen, and always sent as plain
 *  strings from form inputs. */
interface PatientDetailsForm {
  height_cm: string
  weight_kg: string
  phone_number: string
  house_location: string
}

const EMPTY_PATIENT_DETAILS: PatientDetailsForm = {
  height_cm: '',
  weight_kg: '',
  phone_number: '',
  house_location: '',
}

function patientDetailsOf(patient: Patient): PatientDetailsForm {
  return {
    height_cm: patient.height_cm != null ? String(patient.height_cm) : '',
    weight_kg: patient.weight_kg != null ? String(patient.weight_kg) : '',
    phone_number: patient.phone_number ?? '',
    house_location: patient.house_location ?? '',
  }
}

interface PatientDetailResponse {
  patient: Patient
  assessments: Assessment[]
}

function formatEncounterDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' })
}

/** Compact, scannable read of a patient's already-saved assessments — the
 *  same fields the worker just entered, shown the way they will read back
 *  later. Never the current, unsaved form (that only exists client-side
 *  until "Accept & Record Assessment" actually persists it). */
function PreviousAssessmentsList({ assessments }: { assessments: Assessment[] }) {
  const { t } = useTranslation('assessments')

  if (assessments.length === 0) {
    return <Empty>{t('patientHistory.noPrevious')}</Empty>
  }

  return (
    <ul className="max-h-[28rem] space-y-3 overflow-y-auto pr-1">
      {assessments.map((assessment) => (
        <li key={assessment.id} className="rounded-md border border-ink-200 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink-800">
              {formatEncounterDate(assessment.encounter_date)}
            </span>
            <TriagePill level={assessment.triage_level} />
          </div>

          {(assessment.symptoms.length > 0 || assessment.other_symptom_text) && (
            <p className="mt-1.5 text-xs text-ink-600">
              <span className="font-medium text-ink-700">{t('patientHistory.symptomsLabel')} </span>
              {[
                ...assessment.symptoms.map((s) => symptomLabel(t, s)),
                assessment.other_symptom_text,
              ]
                .filter(Boolean)
                .join(', ')}
            </p>
          )}

          <p className="mt-1 text-xs text-ink-600">
            <span className="font-medium text-ink-700">{t('patientHistory.durationLabel')} </span>
            {t('patientHistory.durationDaysCount', { count: assessment.duration_days })}
          </p>

          {(assessment.temperature_c != null ||
            assessment.pulse_bpm != null ||
            assessment.respiratory_rate != null ||
            assessment.systolic_bp != null ||
            assessment.diastolic_bp != null ||
            assessment.spo2 != null) && (
            <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-ink-600 sm:grid-cols-3">
              {assessment.temperature_c != null && (
                <span>{t('patientHistory.vitalTemp', { value: assessment.temperature_c })}</span>
              )}
              {assessment.pulse_bpm != null && (
                <span>{t('patientHistory.vitalPulse', { value: assessment.pulse_bpm })}</span>
              )}
              {assessment.respiratory_rate != null && (
                <span>{t('patientHistory.vitalResp', { value: assessment.respiratory_rate })}</span>
              )}
              {(assessment.systolic_bp != null || assessment.diastolic_bp != null) && (
                <span>
                  {t('patientHistory.vitalBp', {
                    systolic: assessment.systolic_bp ?? '—',
                    diastolic: assessment.diastolic_bp ?? '—',
                  })}
                </span>
              )}
              {assessment.spo2 != null && (
                <span>{t('patientHistory.vitalSpo2', { value: assessment.spo2 })}</span>
              )}
            </div>
          )}

          {assessment.sugar_mg_dl != null && (
            <p className="mt-1.5 text-xs text-ink-600">
              <span className="font-medium text-ink-700">{t('patientHistory.bloodSugarLabel')} </span>
              {assessment.sugar_mg_dl} mg/dL
              <br />
              <span className="font-medium text-ink-700">{t('patientHistory.measurementLabel')} </span>
              {assessment.blood_sugar_measurement_type
                ? t(`newAssessment.${SUGAR_MEASUREMENT_KEYS[assessment.blood_sugar_measurement_type]}`)
                : t('patientHistory.notRecorded')}
            </p>
          )}

          {assessment.notes && (
            <p className="mt-1.5 text-xs text-ink-600">
              <span className="font-medium text-ink-700">{t('patientHistory.notesLabel')} </span>
              {assessment.notes}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Only the days the worker actually filled in are sent. */
function timelineOf(form: AssessmentForm) {
  if (!form.day_wise_enabled) return []
  return TIMELINE_DAYS.map((day) => ({
    day,
    detail: (form.day_details[day] ?? '').trim(),
  })).filter((entry) => entry.detail !== '')
}

function toPayload(patientId: number, form: AssessmentForm) {
  const num = (value: string) => (value.trim() === '' ? null : Number(value))
  return {
    patient: patientId,
    symptoms: form.symptoms,
    other_symptom_selected: form.other_selected,
    other_symptom_text: form.other_selected ? form.other_text.trim() : '',
    duration_days: Number(form.duration_days || 0),
    symptom_timeline: timelineOf(form),
    temperature_c: num(form.temperature_c),
    pulse_bpm: num(form.pulse_bpm),
    respiratory_rate: num(form.respiratory_rate),
    systolic_bp: num(form.systolic_bp),
    diastolic_bp: num(form.diastolic_bp),
    spo2: num(form.spo2),
    sugar_mg_dl: num(form.sugar_mg_dl),
    blood_sugar_measurement_type: form.blood_sugar_measurement_type,
    notes: form.notes,
  }
}

type AssessmentType = 'general' | 'pregnancy'

export default function NewAssessment() {
  const { t } = useTranslation('assessments')
  const navigate = useNavigate()
  const { user } = useAuth()
  const patients = useAsync<Patient[]>(() => api.get('/patients/'))

  const [step, setStep] = useState<Step>('choose')
  const [patient, setPatient] = useState<Patient | null>(null)
  const [search, setSearch] = useState('')

  // Which assessment pathway for the current patient — a choice inside this
  // same New Assessment workflow, never a separate portal or route (task
  // §1: "Pregnancy must be another assessment pathway inside the existing
  // New Assessment workflow").
  const [assessmentType, setAssessmentType] = useState<AssessmentType | null>(null)

  const [newPatient, setNewPatient] = useState({ ...EMPTY_PATIENT })
  const [creating, setCreating] = useState(false)
  const [patientError, setPatientError] = useState<string | null>(null)

  // Patient details shown/editable once a patient (new or existing) is on
  // screen for the assessment step — pre-filled from the stored record,
  // blank where nothing has been recorded yet.
  const [patientDetails, setPatientDetails] = useState<PatientDetailsForm>({
    ...EMPTY_PATIENT_DETAILS,
  })

  const [form, setForm] = useState<AssessmentForm>({ ...EMPTY_ASSESSMENT })
  const [support, setSupport] = useState<TriageSupport | null>(null)
  const [busy, setBusy] = useState<'preview' | 'submit' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const list = patients.data ?? []
    const query = search.trim().toLowerCase()
    if (!query) return list
    return list.filter(
      (p) =>
        p.patient_code.toLowerCase().includes(query) ||
        (p.display_name ?? '').toLowerCase().includes(query),
    )
  }, [patients.data, search])

  // The selected patient's own saved encounter history — the same
  // village-scoped read `/worker/patient/:id` already uses, reused here
  // rather than a second history endpoint. Resolves to `null` (no
  // request) while no patient is selected.
  const history = useAsync<PatientDetailResponse | null>(
    () => (patient ? api.get(`/patients/${patient.id}/`) : Promise.resolve(null)),
    [patient?.id],
  )
  // Guards against ever rendering a stale patient's history for the
  // newly-selected one, regardless of exactly when the fetch above
  // resolves relative to this render.
  const historyReady = Boolean(patient && history.data && history.data.patient.id === patient.id)

  // Pre-fill patient details from whichever patient is now on screen — a
  // just-registered one (its own values, just entered) or one selected
  // from search (its stored values, blank where never recorded). Re-runs
  // only when the patient itself changes, so the worker's own edits are
  // never overwritten mid-edit.
  useEffect(() => {
    setPatientDetails(patient ? patientDetailsOf(patient) : { ...EMPTY_PATIENT_DETAILS })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient?.id])

  // Pregnancy eligibility (patient.sex !== 'M') must never carry over from a
  // previously-selected patient — "Change patient" only clears `patient`,
  // so without this a worker who had `assessmentType` already set to
  // 'pregnancy' could pick a different (possibly male) patient and land
  // straight in the Pregnancy flow without ever seeing the type selector
  // again. Resetting here, the same way `patientDetails` resets above,
  // closes that gap for every path that changes `patient`, not just one.
  useEffect(() => {
    setAssessmentType(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patient?.id])

  const set = (key: keyof AssessmentForm, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  /** Clearing the sugar reading clears its measurement type with it — the
   *  two are recorded together or not at all. */
  function setSugar(value: string) {
    setForm((prev) => ({
      ...prev,
      sugar_mg_dl: value,
      blood_sugar_measurement_type: value.trim() === '' ? '' : prev.blood_sugar_measurement_type,
    }))
  }

  const setPatientDetail = (key: keyof PatientDetailsForm, value: string) =>
    setPatientDetails((prev) => ({ ...prev, [key]: value }))

  function toggleSymptom(symptom: string) {
    setSupport(null)
    setForm((prev) => ({
      ...prev,
      symptoms: prev.symptoms.includes(symptom)
        ? prev.symptoms.filter((s) => s !== symptom)
        : [...prev.symptoms, symptom],
    }))
  }

  /** "Other" behaves like the symptom buttons: changing it invalidates a run. */
  function toggleOther() {
    setSupport(null)
    setForm((prev) => ({
      ...prev,
      other_selected: !prev.other_selected,
      // Deselecting clears the description so nothing unseen is submitted.
      other_text: prev.other_selected ? '' : prev.other_text,
    }))
  }

  function setDayDetail(day: number, value: string) {
    setForm((prev) => ({
      ...prev,
      day_details: { ...prev.day_details, [day]: value },
    }))
  }

  function restart() {
    setStep('choose')
    setPatient(null)
    setAssessmentType(null)
    setSupport(null)
    setSaved(null)
    setError(null)
    setForm({ ...EMPTY_ASSESSMENT })
    setNewPatient({ ...EMPTY_PATIENT })
    setPatientError(null)
  }

  async function createPatient(event: FormEvent) {
    event.preventDefault()
    setCreating(true)
    setPatientError(null)
    try {
      const created = await api.post<Patient>('/patients/', {
        display_name: newPatient.display_name.trim(),
        age_years: newPatient.age_years ? Number(newPatient.age_years) : null,
        age_months: newPatient.age_months ? Number(newPatient.age_months) : null,
        sex: newPatient.sex,
        height_cm: newPatient.height_cm.trim() === '' ? null : Number(newPatient.height_cm),
        weight_kg: newPatient.weight_kg.trim() === '' ? null : Number(newPatient.weight_kg),
        phone_number: newPatient.phone_number.trim(),
        house_location: newPatient.house_location.trim(),
        village: user?.village ?? null,
      })
      setPatient(created)
      setStep('assessment')
      patients.reload()
    } catch (err) {
      setPatientError(
        err instanceof Error ? err.message : t('newAssessment.couldNotRegisterPatient'),
      )
    } finally {
      setCreating(false)
    }
  }

  async function runAgents(event: FormEvent) {
    event.preventDefault()
    if (!patient) return
    setBusy('preview')
    setError(null)
    try {
      const response = await api.post<{ support: TriageSupport }>(
        '/assessments/preview/',
        toPayload(patient.id, form),
      )
      setSupport(response.support)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t('newAssessment.couldNotProcess'),
      )
    } finally {
      setBusy(null)
    }
  }

  /** True only when the worker actually changed a patient-detail field from
   *  what was pre-filled — so accepting an assessment for an unchanged
   *  patient never issues a needless write. */
  function patientDetailsChanged(): boolean {
    if (!patient) return false
    const original = patientDetailsOf(patient)
    return (
      patientDetails.height_cm !== original.height_cm ||
      patientDetails.weight_kg !== original.weight_kg ||
      patientDetails.phone_number.trim() !== original.phone_number ||
      patientDetails.house_location.trim() !== original.house_location
    )
  }

  async function submit() {
    if (!patient) return
    setBusy('submit')
    setError(null)
    try {
      if (patientDetailsChanged()) {
        await api.patch<Patient>(`/patients/${patient.id}/`, {
          height_cm:
            patientDetails.height_cm.trim() === ''
              ? null
              : Number(patientDetails.height_cm),
          weight_kg:
            patientDetails.weight_kg.trim() === ''
              ? null
              : Number(patientDetails.weight_kg),
          phone_number: patientDetails.phone_number.trim(),
          house_location: patientDetails.house_location.trim(),
        })
      }
      const response = await api.post<{
        assessment: { id: number; patient: number }
        aggregation: { message: string; week_label: string }
      }>('/assessments/', toPayload(patient.id, form))
      setSaved(response.aggregation.message)
      setTimeout(
        () => navigate(`/worker/patient/${response.assessment.patient}`),
        1600,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : t('newAssessment.couldNotSave'))
      setBusy(null)
    }
  }

  if (patients.loading) return <Loading label={t('patientHistory.loading')} />

  // "Other" without a description records nothing, so it is refused here as
  // well as on the server.
  const otherMissingText = form.other_selected && form.other_text.trim() === ''
  const hasSomethingRecorded =
    form.symptoms.length > 0 || (form.other_selected && !otherMissingText)
  // A sugar reading without its measurement type is an incomplete entry —
  // same "refused before submission, not just at the server" pattern as
  // the "Other" symptom above.
  const sugarMissingMeasurement =
    form.sugar_mg_dl.trim() !== '' && form.blood_sugar_measurement_type === ''
  const canRun =
    patient !== null && hasSomethingRecorded && !otherMissingText && !sugarMissingMeasurement

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">{t('newAssessment.title')}</h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {step === 'choose'
              ? t('newAssessment.chooseWho')
              : patient
                ? `${patient.patient_code} · ${patient.display_name}`
                : t('newAssessment.registerPatient')}
          </p>
        </div>
        {step !== 'choose' && (
          <button className="btn-ghost ml-auto" onClick={restart}>
            {t('common:actions.startOver')}
          </button>
        )}
      </div>

      {/* ---- Step 1: who is this for? ---- */}
      {step === 'choose' && (
        <Card title={t('newAssessment.chooseWho')}>
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              className="rounded-lg border border-ink-200 p-5 text-left hover:border-care-500 hover:bg-care-50/50 transition-colors"
              onClick={() => setStep('new-patient')}
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-care-100 text-care-700 text-lg font-semibold">
                +
              </div>
              <div className="mt-3 text-sm font-semibold text-ink-800">
                {t('newAssessment.newPatient')}
              </div>
              <p className="mt-1 text-xs text-ink-600">
                {t('newAssessment.newPatientHelp')}
              </p>
            </button>

            <button
              className="rounded-lg border border-ink-200 p-5 text-left hover:border-care-500 hover:bg-care-50/50 transition-colors"
              onClick={() => setStep('assessment')}
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-ink-100 text-ink-600">
                <svg
                  viewBox="0 0 20 20"
                  className="h-4 w-4"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="9" cy="9" r="6" />
                  <path d="m14 14 4 4" strokeLinecap="round" />
                </svg>
              </div>
              <div className="mt-3 text-sm font-semibold text-ink-800">
                {t('newAssessment.existingPatient')}
              </div>
              <p className="mt-1 text-xs text-ink-600">
                {t('newAssessment.existingPatientHelp')}
              </p>
            </button>
          </div>

          {patients.error && (
            <div className="mt-4">
              <ErrorNote message={patients.error} onRetry={patients.reload} />
            </div>
          )}
        </Card>
      )}

      {/* ---- Step 2a: register a new patient ---- */}
      {step === 'new-patient' && (
        <Card title={t('newAssessment.patientDetails')}>
          <form onSubmit={createPatient} className="space-y-4 max-w-lg">
            <div>
              <label className="label" htmlFor="name">
                {t('newAssessment.nameOrReference')} *
              </label>
              <input
                id="name"
                className="input"
                value={newPatient.display_name}
                onChange={(e) =>
                  setNewPatient((p) => ({ ...p, display_name: e.target.value }))
                }
                required
              />
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label" htmlFor="age_years">
                  {t('newAssessment.ageYears')}
                </label>
                <input
                  id="age_years"
                  type="number"
                  min={0}
                  max={120}
                  className="input"
                  value={newPatient.age_years}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, age_years: e.target.value }))
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="age_months">
                  {t('newAssessment.ageMonths')}
                </label>
                <input
                  id="age_months"
                  type="number"
                  min={0}
                  max={36}
                  className="input"
                  value={newPatient.age_months}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, age_months: e.target.value }))
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="sex">
                  {t('newAssessment.sex')}
                </label>
                <select
                  id="sex"
                  className="input"
                  value={newPatient.sex}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, sex: e.target.value }))
                  }
                >
                  <option value="U">{t('newAssessment.sexNotStated')}</option>
                  <option value="F">{t('newAssessment.sexFemale')}</option>
                  <option value="M">{t('newAssessment.sexMale')}</option>
                  <option value="O">{t('newAssessment.sexOther')}</option>
                </select>
              </div>
            </div>
            <p className="text-xs text-ink-400 -mt-2">
              {t('newAssessment.ageHelp')}
            </p>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="height_cm">
                  {t('newAssessment.heightCm')}
                </label>
                <input
                  id="height_cm"
                  type="number"
                  min={0}
                  step="0.1"
                  className="input"
                  value={newPatient.height_cm}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, height_cm: e.target.value }))
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="weight_kg">
                  {t('newAssessment.weightKg')}
                </label>
                <input
                  id="weight_kg"
                  type="number"
                  min={0}
                  step="0.1"
                  className="input"
                  value={newPatient.weight_kg}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, weight_kg: e.target.value }))
                  }
                />
              </div>
            </div>

            <div>
              <label className="label" htmlFor="phone_number">
                {t('newAssessment.phoneNumber')}
              </label>
              <input
                id="phone_number"
                className="input"
                inputMode="tel"
                value={newPatient.phone_number}
                onChange={(e) =>
                  setNewPatient((p) => ({ ...p, phone_number: e.target.value }))
                }
              />
            </div>

            <div>
              <label className="label" htmlFor="house_location">
                {t('newAssessment.houseLocation')}
              </label>
              <input
                id="house_location"
                className="input"
                placeholder={t('newAssessment.houseLocationPlaceholder')}
                value={newPatient.house_location}
                onChange={(e) =>
                  setNewPatient((p) => ({ ...p, house_location: e.target.value }))
                }
              />
            </div>

            <div className="rounded-md bg-ink-50 border border-ink-200 px-3 py-2 text-xs text-ink-600">
              {t('newAssessment.villageLabel')} <span className="font-medium">{user?.village_name}</span>{' '}
              — {t('newAssessment.villageNote')}
            </div>

            {patientError && <ErrorNote message={patientError} />}

            <div className="flex gap-2">
              <button
                type="submit"
                className="btn-care"
                disabled={creating || !newPatient.display_name.trim()}
              >
                {creating ? t('newAssessment.registering') : t('newAssessment.registerAndContinue')}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setStep('choose')}
              >
                {t('common:actions.back')}
              </button>
            </div>
          </form>
        </Card>
      )}

      {/* ---- Step 2b / 3: pick a patient, then assess ---- */}
      {step === 'assessment' && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="space-y-6">
            {!patient && (
              <Card title={t('newAssessment.selectPatient')}>
                <input
                  className="input"
                  placeholder={t('newAssessment.searchPlaceholder')}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                />
                <ul className="mt-3 max-h-72 overflow-y-auto space-y-1.5">
                  {filtered.length === 0 && (
                    <li className="text-sm text-ink-400 py-4 text-center">
                      {t('newAssessment.noMatchingPatient')}{' '}
                      <button
                        className="text-care-700 hover:underline"
                        onClick={() => setStep('new-patient')}
                      >
                        {t('newAssessment.registerNewPatient')}
                      </button>
                      .
                    </li>
                  )}
                  {filtered.map((option) => (
                    <li key={option.id}>
                      <button
                        className="w-full text-left rounded-md border border-ink-200 px-3 py-2 hover:border-care-500 hover:bg-care-50/40"
                        onClick={() => setPatient(option)}
                      >
                        <div className="text-sm font-medium">
                          {option.patient_code}
                        </div>
                        <div className="text-xs text-ink-400">
                          {option.display_name} ·{' '}
                          {option.age_years
                            ? `${option.age_years}y`
                            : `${option.age_months}m`}{' '}
                          · {t('newAssessment.previousAssessmentCount', { count: option.assessment_count })}
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  className="btn-ghost mt-3 w-full"
                  onClick={() => setStep('choose')}
                >
                  {t('common:actions.back')}
                </button>
              </Card>
            )}

            {patient && !assessmentType && (
              <Card
                title={t('newAssessment.assessmentType')}
                action={
                  <button
                    className="text-xs text-ink-400 hover:text-ink-600"
                    onClick={() => setPatient(null)}
                  >
                    {t('common:actions.changePatient')}
                  </button>
                }
              >
                <div className="grid gap-3 sm:grid-cols-2">
                  <button
                    className="rounded-lg border border-ink-200 p-5 text-left hover:border-care-500 hover:bg-care-50/50 transition-colors"
                    onClick={() => setAssessmentType('general')}
                  >
                    <div className="text-sm font-semibold text-ink-800">
                      {t('newAssessment.generalAssessment')}
                    </div>
                    <p className="mt-1 text-xs text-ink-600">
                      {t('newAssessment.generalAssessmentDescription')}
                    </p>
                  </button>
                  {patient.sex === 'M' ? (
                    <div
                      className="rounded-lg border border-ink-200 bg-ink-50 p-5 text-left opacity-60"
                      aria-disabled="true"
                      title={t('newAssessment.pregnancyNotAvailableForPatient')}
                    >
                      <div className="text-sm font-semibold text-ink-400">
                        {t('newAssessment.pregnancy')}
                      </div>
                      <p className="mt-1 text-xs text-ink-400">
                        {t('newAssessment.pregnancyNotAvailableForPatient')}
                      </p>
                    </div>
                  ) : (
                    <button
                      className="rounded-lg border border-ink-200 p-5 text-left hover:border-care-500 hover:bg-care-50/50 transition-colors"
                      onClick={() => setAssessmentType('pregnancy')}
                    >
                      <div className="text-sm font-semibold text-ink-800">{t('newAssessment.pregnancy')}</div>
                      <p className="mt-1 text-xs text-ink-600">
                        {t('newAssessment.pregnancyDescription')}
                      </p>
                    </button>
                  )}
                </div>
              </Card>
            )}

            {patient && assessmentType === 'general' && (
              <Card
                title={t('newAssessment.assessment')}
                action={
                  <div className="flex items-center gap-3">
                    <button
                      className="text-xs text-ink-400 hover:text-ink-600"
                      onClick={() => setAssessmentType(null)}
                    >
                      {t('common:actions.changeAssessmentType')}
                    </button>
                    <button
                      className="text-xs text-ink-400 hover:text-ink-600"
                      onClick={() => setPatient(null)}
                    >
                      {t('common:actions.changePatient')}
                    </button>
                  </div>
                }
              >
                <form onSubmit={runAgents} className="space-y-5">
                  <fieldset>
                    <legend className="label">{t('newAssessment.patientDetails')}</legend>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="label" htmlFor="pd_height">
                          {t('newAssessment.heightCm')}
                        </label>
                        <input
                          id="pd_height"
                          type="number"
                          min={0}
                          step="0.1"
                          className="input"
                          value={patientDetails.height_cm}
                          onChange={(e) => setPatientDetail('height_cm', e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="label" htmlFor="pd_weight">
                          {t('newAssessment.weightKg')}
                        </label>
                        <input
                          id="pd_weight"
                          type="number"
                          min={0}
                          step="0.1"
                          className="input"
                          value={patientDetails.weight_kg}
                          onChange={(e) => setPatientDetail('weight_kg', e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="label" htmlFor="pd_phone">
                          {t('newAssessment.phoneNumber')}
                        </label>
                        <input
                          id="pd_phone"
                          className="input"
                          inputMode="tel"
                          value={patientDetails.phone_number}
                          onChange={(e) => setPatientDetail('phone_number', e.target.value)}
                        />
                      </div>
                      <div>
                        <label className="label" htmlFor="pd_location">
                          {t('newAssessment.houseLocation')}
                        </label>
                        <input
                          id="pd_location"
                          className="input"
                          placeholder={t('newAssessment.houseLocationPlaceholderShort')}
                          value={patientDetails.house_location}
                          onChange={(e) => setPatientDetail('house_location', e.target.value)}
                        />
                      </div>
                    </div>
                  </fieldset>

                  <div>
                    <span className="label">{t('newAssessment.symptoms')}</span>
                    <div className="flex flex-wrap gap-1.5">
                      {SYMPTOM_OPTIONS.map((symptom) => {
                        const on = form.symptoms.includes(symptom)
                        return (
                          <button
                            type="button"
                            key={symptom}
                            onClick={() => toggleSymptom(symptom)}
                            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                              on
                                ? 'bg-care-600 border-care-600 text-white'
                                : 'bg-white border-ink-200 text-ink-600 hover:border-care-500'
                            }`}
                          >
                            {symptomLabel(t, symptom)}
                          </button>
                        )
                      })}

                      {/* Optional, for anything the list above cannot say. */}
                      <button
                        type="button"
                        onClick={toggleOther}
                        aria-pressed={form.other_selected}
                        className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                          form.other_selected
                            ? 'bg-care-600 border-care-600 text-white'
                            : 'bg-white border-dashed border-ink-300 text-ink-600 hover:border-care-500'
                        }`}
                      >
                        {t('newAssessment.other')}
                      </button>
                    </div>

                    {form.other_selected && (
                      <div className="mt-3">
                        <label className="label" htmlFor="other_symptom">
                          {t('newAssessment.describeSymptom')} *
                        </label>
                        <textarea
                          id="other_symptom"
                          rows={2}
                          className="input"
                          placeholder={t('newAssessment.describeSymptomPlaceholder')}
                          value={form.other_text}
                          onChange={(e) => set('other_text', e.target.value)}
                        />
                        {otherMissingText ? (
                          <p className="mt-1 text-xs text-red-600">
                            {t('newAssessment.describeSymptomError')}
                          </p>
                        ) : (
                          <p className="mt-1 text-xs text-ink-400">
                            {t('newAssessment.describeSymptomHelp')}
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="label" htmlFor="duration">
                      {t('newAssessment.durationDays')}
                    </label>
                    <input
                      id="duration"
                      type="number"
                      min={0}
                      max={365}
                      className="input"
                      value={form.duration_days}
                      onChange={(e) => set('duration_days', e.target.value)}
                    />

                    {/* Optional extra detail layer — off by default, and it
                        never replaces the duration recorded above. */}
                    <div className="mt-3 rounded-md border border-ink-200 bg-ink-50/60 px-3 py-2.5">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-ink-300 text-care-600 focus:ring-care-500/30"
                          checked={form.day_wise_enabled}
                          onChange={(e) =>
                            setForm((prev) => ({
                              ...prev,
                              day_wise_enabled: e.target.checked,
                            }))
                          }
                        />
                        <span className="text-xs font-medium text-ink-600">
                          {t('newAssessment.dayWiseToggle')}
                        </span>
                      </label>

                      {form.day_wise_enabled && (
                        <div className="mt-3 space-y-2.5">
                          {TIMELINE_DAYS.map((day) => (
                            <div key={day}>
                              <label className="label" htmlFor={`day-${day}`}>
                                {t('newAssessment.day', { n: day })}
                              </label>
                              <textarea
                                id={`day-${day}`}
                                rows={2}
                                className="input bg-white"
                                placeholder={
                                  day === 1
                                    ? t('newAssessment.dayPlaceholderFirst')
                                    : t('newAssessment.dayPlaceholderOther')
                                }
                                value={form.day_details[day] ?? ''}
                                onChange={(e) =>
                                  setDayDetail(day, e.target.value)
                                }
                              />
                            </div>
                          ))}
                          <p className="text-xs text-ink-400">
                            {t('newAssessment.dayWiseHelp')}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>

                  <fieldset>
                    <legend className="label">
                      {t('newAssessment.vitalSigns')}
                    </legend>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      {VITAL_FIELDS.map(([key, labelKey, step2]) => (
                        <div key={key}>
                          <label className="label" htmlFor={key}>
                            {t(`newAssessment.${labelKey}`)}
                          </label>
                          <input
                            id={key}
                            type="number"
                            step={step2}
                            className="input"
                            value={form[key]}
                            onChange={(e) => set(key, e.target.value)}
                          />
                        </div>
                      ))}
                    </div>

                    <div className="mt-3">
                      <label className="label" htmlFor="sugar_mg_dl">
                        {t('newAssessment.bloodSugar')}
                      </label>
                      <input
                        id="sugar_mg_dl"
                        type="number"
                        min={0}
                        step="1"
                        className="input max-w-[10rem]"
                        value={form.sugar_mg_dl}
                        onChange={(e) => setSugar(e.target.value)}
                      />

                      {form.sugar_mg_dl.trim() !== '' && (
                        <div className="mt-2">
                          <span className="label">{t('newAssessment.measurement')}</span>
                          <div className="flex flex-wrap gap-3">
                            {SUGAR_MEASUREMENT_OPTIONS.map((value) => (
                              <label
                                key={value}
                                className="flex items-center gap-1.5 text-xs text-ink-700"
                              >
                                <input
                                  type="radio"
                                  name="blood_sugar_measurement_type"
                                  checked={form.blood_sugar_measurement_type === value}
                                  onChange={() => set('blood_sugar_measurement_type', value)}
                                />
                                {t(`newAssessment.${SUGAR_MEASUREMENT_KEYS[value]}`)}
                              </label>
                            ))}
                          </div>
                          {sugarMissingMeasurement && (
                            <p className="mt-1 text-xs text-red-600">
                              {t('newAssessment.measurementRequired')}
                            </p>
                          )}
                        </div>
                      )}
                    </div>
                  </fieldset>

                  <div>
                    <label className="label" htmlFor="notes">
                      {t('newAssessment.notes')}
                    </label>
                    <textarea
                      id="notes"
                      rows={2}
                      className="input"
                      value={form.notes}
                      onChange={(e) => set('notes', e.target.value)}
                    />
                  </div>

                  {error && <ErrorNote message={error} />}

                  <button
                    type="submit"
                    className="btn-care w-full"
                    disabled={!canRun || busy !== null}
                  >
                    {busy === 'preview' ? t('newAssessment.processing') : t('newAssessment.getAiSuggestion')}
                  </button>
                </form>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            {assessmentType === 'general' && (!support ? (
              <Card title={t('patientHistory.title')}>
                {!patient ? (
                  <p className="text-sm text-ink-400 py-8 text-center">
                    {t('patientHistory.selectPatientPrompt')}
                  </p>
                ) : !historyReady ? (
                  history.error ? (
                    <ErrorNote message={history.error} onRetry={history.reload} />
                  ) : (
                    <Loading label={t('patientHistory.loadingHistory')} />
                  )
                ) : (
                  <PreviousAssessmentsList assessments={history.data?.assessments ?? []} />
                )}
              </Card>
            ) : (
              <Card title={t('triageSupport.title')}>
                <TriageSupportPanel
                  support={support}
                  vitals={{
                    temperature_c: form.temperature_c,
                    pulse_bpm: form.pulse_bpm,
                    respiratory_rate: form.respiratory_rate,
                    systolic_bp: form.systolic_bp,
                    diastolic_bp: form.diastolic_bp,
                    spo2: form.spo2,
                  }}
                />

                {support && (
                  <RagGuidancePanel
                    fetcher={() =>
                      api.post<RagResponse>('/rag/ruralcare/', {
                        triage_level: support.triage_level,
                        contributing_factors: support.contributing_factors,
                        syndrome_groups: Object.keys(support.syndrome_groups),
                        referral_pathway: support.referral_pathway,
                      })
                    }
                    deps={[support.triage_level, support.referral_pathway]}
                  />
                )}

                {saved ? (
                  <div className="mt-5 rounded-md border border-care-200 bg-care-50 px-3 py-2 text-sm text-care-700">
                    {saved}
                  </div>
                ) : (
                  <div className="mt-5 flex gap-2">
                    <button
                      className="btn-care flex-1"
                      onClick={submit}
                      disabled={busy !== null}
                    >
                      {busy === 'submit'
                        ? t('newAssessment.saving')
                        : t('newAssessment.acceptAndRecord')}
                    </button>
                    <button
                      className="btn-ghost"
                      onClick={() => setSupport(null)}
                      disabled={busy !== null}
                    >
                      {t('newAssessment.reviseAssessment')}
                    </button>
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      )}

      {step === 'assessment' && patient && assessmentType === 'pregnancy' && patient.sex !== 'M' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <p className="text-sm text-ink-600">
              {patient.patient_code} · {patient.display_name}
            </p>
            <button className="btn-ghost text-xs" onClick={() => setAssessmentType(null)}>
              {t('common:actions.changeAssessmentType')}
            </button>
          </div>
          <PregnancyAssessmentFlow patientId={patient.id} />
        </div>
      )}
    </div>
  )
}
