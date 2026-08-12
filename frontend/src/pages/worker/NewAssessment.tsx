import { type FormEvent, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { AgentTrace } from '@/components/AgentTrace'
import { TriageSupportPanel } from '@/components/TriageSupport'
import { Card, Disclaimer, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type { Patient, TriageSupport } from '@/types'

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

type Step = 'choose' | 'new-patient' | 'assessment'

interface AssessmentForm {
  symptoms: string[]
  duration_days: string
  temperature_c: string
  pulse_bpm: string
  respiratory_rate: string
  systolic_bp: string
  diastolic_bp: string
  spo2: string
  notes: string
}

const EMPTY_ASSESSMENT: AssessmentForm = {
  symptoms: [],
  duration_days: '',
  temperature_c: '',
  pulse_bpm: '',
  respiratory_rate: '',
  systolic_bp: '',
  diastolic_bp: '',
  spo2: '',
  notes: '',
}

const EMPTY_PATIENT = {
  display_name: '',
  patient_code: '',
  age_years: '',
  age_months: '',
  sex: 'U',
}

function toPayload(patientId: number, form: AssessmentForm) {
  const num = (value: string) => (value.trim() === '' ? null : Number(value))
  return {
    patient: patientId,
    symptoms: form.symptoms,
    duration_days: Number(form.duration_days || 0),
    temperature_c: num(form.temperature_c),
    pulse_bpm: num(form.pulse_bpm),
    respiratory_rate: num(form.respiratory_rate),
    systolic_bp: num(form.systolic_bp),
    diastolic_bp: num(form.diastolic_bp),
    spo2: num(form.spo2),
    notes: form.notes,
  }
}

export default function NewAssessment() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const patients = useAsync<Patient[]>(() => api.get('/patients/'))

  const [step, setStep] = useState<Step>('choose')
  const [patient, setPatient] = useState<Patient | null>(null)
  const [search, setSearch] = useState('')

  const [newPatient, setNewPatient] = useState({ ...EMPTY_PATIENT })
  const [creating, setCreating] = useState(false)
  const [patientError, setPatientError] = useState<string | null>(null)

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

  const set = (key: keyof AssessmentForm, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  function toggleSymptom(symptom: string) {
    setSupport(null)
    setForm((prev) => ({
      ...prev,
      symptoms: prev.symptoms.includes(symptom)
        ? prev.symptoms.filter((s) => s !== symptom)
        : [...prev.symptoms, symptom],
    }))
  }

  function restart() {
    setStep('choose')
    setPatient(null)
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
        patient_code: newPatient.patient_code.trim(),
        age_years: newPatient.age_years ? Number(newPatient.age_years) : null,
        age_months: newPatient.age_months ? Number(newPatient.age_months) : null,
        sex: newPatient.sex,
        village: user?.village ?? null,
      })
      setPatient(created)
      setStep('assessment')
      patients.reload()
    } catch (err) {
      setPatientError(
        err instanceof Error ? err.message : 'Could not register the patient.',
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
        err instanceof Error ? err.message : 'Could not process the assessment.',
      )
    } finally {
      setBusy(null)
    }
  }

  async function submit() {
    if (!patient) return
    setBusy('submit')
    setError(null)
    try {
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
      setError(err instanceof Error ? err.message : 'Could not save.')
      setBusy(null)
    }
  }

  if (patients.loading) return <Loading label="Loading…" />

  const canRun = patient !== null && form.symptoms.length > 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">New assessment</h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {step === 'choose'
              ? 'Who is this assessment for?'
              : patient
                ? `${patient.patient_code} · ${patient.display_name}`
                : 'Register the patient'}
          </p>
        </div>
        {step !== 'choose' && (
          <button className="btn-ghost ml-auto" onClick={restart}>
            Start over
          </button>
        )}
      </div>

      {/* ---- Step 1: who is this for? ---- */}
      {step === 'choose' && (
        <Card title="Who is this assessment for?">
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              className="rounded-lg border border-ink-200 p-5 text-left hover:border-care-500 hover:bg-care-50/50 transition-colors"
              onClick={() => setStep('new-patient')}
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-care-100 text-care-700 text-lg font-semibold">
                +
              </div>
              <div className="mt-3 text-sm font-semibold text-ink-800">
                New patient
              </div>
              <p className="mt-1 text-xs text-ink-600">
                Register someone being seen for the first time, then continue
                straight into the assessment.
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
                Existing patient
              </div>
              <p className="mt-1 text-xs text-ink-600">
                Find someone already registered and add a new assessment to
                their record.
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
        <Card title="Patient details">
          <form onSubmit={createPatient} className="space-y-4 max-w-lg">
            <div>
              <label className="label" htmlFor="name">
                Name or local reference *
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
                  Age (years)
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
                  or months
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
                  Sex
                </label>
                <select
                  id="sex"
                  className="input"
                  value={newPatient.sex}
                  onChange={(e) =>
                    setNewPatient((p) => ({ ...p, sex: e.target.value }))
                  }
                >
                  <option value="U">Not stated</option>
                  <option value="F">Female</option>
                  <option value="M">Male</option>
                  <option value="O">Other</option>
                </select>
              </div>
            </div>
            <p className="text-xs text-ink-400 -mt-2">
              Age in years, or in months for infants.
            </p>

            <div>
              <label className="label" htmlFor="code">
                Patient identifier
              </label>
              <input
                id="code"
                className="input"
                placeholder="Leave blank to generate automatically"
                value={newPatient.patient_code}
                onChange={(e) =>
                  setNewPatient((p) => ({ ...p, patient_code: e.target.value }))
                }
              />
            </div>

            <div className="rounded-md bg-ink-50 border border-ink-200 px-3 py-2 text-xs text-ink-600">
              Village: <span className="font-medium">{user?.village_name}</span>{' '}
              — patients you register belong to your own area.
            </div>

            {patientError && <ErrorNote message={patientError} />}

            <div className="flex gap-2">
              <button
                type="submit"
                className="btn-care"
                disabled={creating || !newPatient.display_name.trim()}
              >
                {creating ? 'Registering…' : 'Register and continue'}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setStep('choose')}
              >
                Back
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
              <Card title="Select patient">
                <input
                  className="input"
                  placeholder="Search by name or identifier…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                />
                <ul className="mt-3 max-h-72 overflow-y-auto space-y-1.5">
                  {filtered.length === 0 && (
                    <li className="text-sm text-ink-400 py-4 text-center">
                      No matching patient.{' '}
                      <button
                        className="text-care-700 hover:underline"
                        onClick={() => setStep('new-patient')}
                      >
                        Register a new patient
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
                          · {option.assessment_count} previous assessment(s)
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
                <button
                  className="btn-ghost mt-3 w-full"
                  onClick={() => setStep('choose')}
                >
                  Back
                </button>
              </Card>
            )}

            {patient && (
              <Card
                title="Assessment"
                action={
                  <button
                    className="text-xs text-ink-400 hover:text-ink-600"
                    onClick={() => setPatient(null)}
                  >
                    Change patient
                  </button>
                }
              >
                <form onSubmit={runAgents} className="space-y-5">
                  <div>
                    <span className="label">Symptoms</span>
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
                            {symptom.replace(/_/g, ' ')}
                          </button>
                        )
                      })}
                    </div>
                  </div>

                  <div>
                    <label className="label" htmlFor="duration">
                      Duration (days)
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
                  </div>

                  <fieldset>
                    <legend className="label">
                      Vital signs (where available)
                    </legend>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      {(
                        [
                          ['temperature_c', 'Temp °C', '0.1'],
                          ['pulse_bpm', 'Pulse /min', '1'],
                          ['respiratory_rate', 'Resp /min', '1'],
                          ['systolic_bp', 'Systolic', '1'],
                          ['diastolic_bp', 'Diastolic', '1'],
                          ['spo2', 'SpO₂ %', '1'],
                        ] as const
                      ).map(([key, label, step2]) => (
                        <div key={key}>
                          <label className="label" htmlFor={key}>
                            {label}
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
                  </fieldset>

                  <div>
                    <label className="label" htmlFor="notes">
                      Notes
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
                    {busy === 'preview' ? 'Processing…' : 'Get AI suggestion'}
                  </button>
                  <Disclaimer />
                </form>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            {!support ? (
              <Card title="Triage support">
                <p className="text-sm text-ink-400 py-8 text-center">
                  {patient
                    ? 'Record the presentation, then select Get AI suggestion.'
                    : 'Select a patient to begin.'}
                </p>
              </Card>
            ) : (
              <>
                <Card title="Triage support">
                  <TriageSupportPanel support={support} />

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
                          ? 'Saving…'
                          : 'Accept and record assessment'}
                      </button>
                      <button
                        className="btn-ghost"
                        onClick={() => setSupport(null)}
                        disabled={busy !== null}
                      >
                        Revise
                      </button>
                    </div>
                  )}
                </Card>

                <Card title="How this was processed">
                  <AgentTrace trace={support.agent_trace} />
                </Card>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
