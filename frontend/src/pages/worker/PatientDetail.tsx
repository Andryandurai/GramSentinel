import { Link, useParams } from 'react-router-dom'

import {
  Card,
  Disclaimer,
  Empty,
  ErrorNote,
  Loading,
  TriagePill,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { Assessment, Patient } from '@/types'

export default function PatientDetail() {
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<{
    patient: Patient
    assessments: Assessment[]
  }>(() => api.get(`/patients/${id}/`), [id])

  if (loading) return <Loading label="Loading patient record…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const { patient, assessments } = data

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <Link
            to="/worker/dashboard"
            className="text-xs text-ink-400 hover:text-ink-600"
          >
            ← Dashboard
          </Link>
          <h1 className="text-xl font-semibold tracking-tight mt-1">
            {patient.patient_code}
          </h1>
          <p className="text-sm text-ink-600">
            {patient.display_name} ·{' '}
            {patient.age_years
              ? `${patient.age_years} years`
              : `${patient.age_months} months`}{' '}
            · {patient.village_name}
          </p>
        </div>
        <Link to="/worker/assessment/new" className="btn-care ml-auto">
          New assessment
        </Link>
      </div>

      <Card title={`Encounter history (${assessments.length})`}>
        {assessments.length === 0 ? (
          <Empty>No assessments recorded for this patient.</Empty>
        ) : (
          <ol className="space-y-3">
            {assessments.map((assessment) => (
              <li
                key={assessment.id}
                className="rounded-md border border-ink-200 p-4"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <TriagePill level={assessment.triage_level} />
                  <span className="text-sm text-ink-600">
                    {assessment.encounter_date}
                  </span>
                  <span className="text-xs text-ink-400">
                    {assessment.duration_days} day(s) ·{' '}
                    {assessment.primary_category.toLowerCase()}
                  </span>
                  {assessment.escalation_forced && (
                    <span className="pill bg-red-100 text-red-700">
                      escalation forced
                    </span>
                  )}
                  <span className="ml-auto text-xs text-ink-400">
                    {assessment.worker_name}
                  </span>
                </div>

                <p className="mt-2 text-sm text-ink-800">
                  {assessment.reasoning_summary}
                </p>
                <p className="mt-1 text-sm text-ink-600">
                  {assessment.referral_recommendation}
                </p>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {assessment.symptoms.map((symptom) => (
                    <span
                      key={symptom}
                      className="pill bg-ink-100 text-ink-600 font-normal"
                    >
                      {symptom.replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>

                {assessment.aggregated_at && (
                  <p className="mt-3 text-xs text-care-700 border-t border-ink-100 pt-2">
                    Contributed to the community signal as an anonymised count
                    only.
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
        <Disclaimer className="mt-5" />
      </Card>
    </div>
  )
}
