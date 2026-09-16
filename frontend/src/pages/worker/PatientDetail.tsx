import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  Card,
  Empty,
  ErrorNote,
  FollowUpPill,
  Loading,
  TriagePill,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { Assessment, FollowUp, Patient } from '@/types'

export default function PatientDetail() {
  const { t } = useTranslation('worker')
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<{
    patient: Patient
    assessments: Assessment[]
    followups: FollowUp[]
    followup_summary: {
      pending_count: number
      next_due_date: string | null
      last_assessment_date: string | null
      empty_message: string
    }
  }>(() => api.get(`/patients/${id}/`), [id])

  if (loading) return <Loading label={t('patientDetail.loadingRecord')} />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const { patient, assessments } = data
  const followups = data.followups ?? []
  const followupSummary = data.followup_summary

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <Link
            to="/worker/dashboard"
            className="text-xs text-ink-400 hover:text-ink-600"
          >
            ← {t('patientDetail.backToDashboard')}
          </Link>
          <h1 className="text-xl font-semibold tracking-tight mt-1">
            {patient.patient_code}
          </h1>
          <p className="text-sm text-ink-600">
            {patient.display_name} ·{' '}
            {patient.age_years
              ? t('patientDetail.ageYears', { count: patient.age_years })
              : t('patientDetail.ageMonths', { count: patient.age_months })}{' '}
            · {patient.village_name}
          </p>
        </div>
        <Link to="/worker/assessment/new" className="btn-care ml-auto">
          {t('patientDetail.newAssessment')}
        </Link>
      </div>

      {/* Follow-ups for this patient — what the dashboard's Pending
          Follow-ups card links through to. */}
      <Card
        title={t('patientDetail.followupsCount', { count: followups.length })}
        action={
          followupSummary?.pending_count ? (
            <span className="text-xs text-ink-400">
              {t('patientDetail.pendingCount', { count: followupSummary.pending_count })}
              {followupSummary.next_due_date
                ? ` · ${t('patientDetail.nextDue', { date: followupSummary.next_due_date })}`
                : ''}
            </span>
          ) : null
        }
      >
        {followups.length === 0 ? (
          <Empty>
            {followupSummary?.empty_message ||
              t('patientDetail.noFollowupsRecorded')}
          </Empty>
        ) : (
          <ul className="space-y-2">
            {followups.map((followup) => (
              <li
                key={followup.id}
                className="rounded-md border border-ink-200 px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <FollowUpPill
                    status={followup.followup_status}
                    label={followup.followup_status_label}
                  />
                  <span className="font-mono text-sm text-ink-800">
                    {followup.due_date || '—'}
                  </span>
                  <span className="text-xs text-ink-400">
                    {followup.due_description}
                  </span>
                  {followup.assessment && (
                    <span className="ml-auto text-xs text-ink-400">
                      {t('patientDetail.fromAssessment', { id: followup.assessment })}
                    </span>
                  )}
                </div>
                {followup.notes && (
                  <p className="mt-1 text-sm text-ink-600">{followup.notes}</p>
                )}
              </li>
            ))}
          </ul>
        )}
        {assessments.length === 0 && followups.length > 0 && (
          <p className="mt-3 text-xs text-ink-400">
            {t('patientDetail.noAssessmentYetNote')}
          </p>
        )}
        {followupSummary?.last_assessment_date && (
          <p className="mt-3 border-t border-ink-200 pt-3 text-xs text-ink-400">
            {t('patientDetail.mostRecentAssessment', { date: followupSummary.last_assessment_date })}
          </p>
        )}
      </Card>

      <Card title={t('patientDetail.encounterHistoryCount', { count: assessments.length })}>
        {assessments.length === 0 ? (
          <Empty>{t('patientDetail.noAssessmentsRecorded')}</Empty>
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
                    {t('dashboard.dayCount', { count: assessment.duration_days })} ·{' '}
                    {assessment.primary_category.toLowerCase()}
                  </span>
                  {assessment.escalation_forced && (
                    <span className="pill bg-red-100 text-red-700">
                      {t('dashboard.escalationForced')}
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
                  {assessment.other_symptom_text && (
                    <span className="pill bg-ink-100 text-ink-600 font-normal">
                      other
                    </span>
                  )}
                </div>

                {/* Only rendered when the worker recorded them. Assessments
                    from before these fields existed simply have neither. */}
                {assessment.other_symptom_text && (
                  <p className="mt-3 text-sm text-ink-800">
                    <span className="text-xs font-medium text-ink-500">
                      {t('patientDetail.otherLabel')}{' '}
                    </span>
                    {assessment.other_symptom_text}
                  </p>
                )}

                {assessment.symptom_timeline?.length > 0 && (
                  <div className="mt-3">
                    <div className="text-xs font-medium text-ink-500">
                      {t('patientDetail.dayWiseDetails')}
                    </div>
                    <ul className="mt-1 space-y-0.5">
                      {assessment.symptom_timeline.map((entry) => (
                        <li key={entry.day} className="text-sm text-ink-800">
                          <span className="text-xs font-medium text-ink-500">
                            {t('patientDetail.dayPrefix', { day: entry.day })}{' '}
                          </span>
                          {entry.detail}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {assessment.aggregated_at && (
                  <p className="mt-3 text-xs text-care-700 border-t border-ink-100 pt-2">
                    {t('patientDetail.contributedAnonymised')}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  )
}
