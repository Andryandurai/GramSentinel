import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  Card,
  Empty,
  ErrorNote,
  FollowUpPill,
  Loading,
  Stat,
  TriagePill,
} from '@/components/ui'
import { CommunityMap } from '@/components/CommunityMap'
import { RealWorldCommunityProfile } from '@/components/RealWorldCommunityProfile'
import { PregnancySummaryCard } from '@/components/worker/PregnancySummaryCard'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { SymptomSummary, WorkerDashboard } from '@/types'

const ALL_WEEKS = 'all'
const ALL_PATIENTS = 'all'

/**
 * Reported symptom counts for the selected period.
 *
 * Counts of people, not of cases: the same person recorded with fever and
 * headache appears in both rows but only once in the total. The wording is
 * deliberately "reported symptoms" throughout — nothing here is a diagnosis.
 */
function SymptomSummaryCard({
  summary,
  onCreateReport,
}: {
  summary: SymptomSummary | undefined
  onCreateReport: () => void
}) {
  const { t } = useTranslation('worker')

  if (!summary) return null

  const max = summary.rows.reduce((top, row) => Math.max(top, row.count), 0) || 1

  return (
    <Card
      title={t('dashboard.symptomSummaryTitle')}
      action={
        <span className="text-xs text-ink-400">
          {summary.is_all_weeks ? t('dashboard.allWeeks') : summary.period_label}
        </span>
      }
    >
      {summary.is_empty ? (
        <>
          <Empty>{summary.empty_message || t('dashboard.noAssessmentsYet')}</Empty>
          <p className="-mt-3 text-center text-xs text-ink-400">
            {t('dashboard.symptomSummaryHint')}
          </p>
        </>
      ) : (
        <>
          <p className="text-xs text-ink-400 mb-3">{t('dashboard.peopleWithReportedSymptoms')}</p>
          <ul className="space-y-1.5">
            {summary.rows.map((row) => (
              <li key={row.key} className="flex items-center gap-3">
                <span
                  className="w-44 shrink-0 truncate text-sm text-ink-800"
                  title={row.hint || row.label}
                >
                  {row.label}
                </span>
                <span className="h-3.5 flex-1 rounded bg-ink-100 overflow-hidden">
                  <span
                    className="block h-full rounded bg-care-500"
                    style={{
                      width: `${Math.max(4, Math.round((row.count / max) * 100))}%`,
                    }}
                  />
                </span>
                <span className="w-10 shrink-0 text-right font-mono text-sm tabular-nums">
                  {row.count}
                </span>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 border-t border-ink-200 pt-3">
            <span className="text-sm font-medium text-ink-800">
              {t('dashboard.totalPeopleAssessed')}
            </span>
            <span className="font-mono text-lg font-semibold tabular-nums">
              {summary.total_people_assessed}
            </span>
          </div>
          <p className="mt-1 text-xs text-ink-400">
            {t('dashboard.assessmentCountNote', { count: summary.assessment_count })}
          </p>

          <button className="btn-ghost mt-4 w-full" onClick={onCreateReport}>
            {t('dashboard.createCommunityReport')} →
          </button>
        </>
      )}
    </Card>
  )
}

export default function WorkerDashboardPage() {
  const { t } = useTranslation('worker')
  const navigate = useNavigate()
  const [week, setWeek] = useState(ALL_WEEKS)
  const [followupPatient, setFollowupPatient] = useState(ALL_PATIENTS)
  const { data, loading, error, reload } = useAsync<WorkerDashboard>(
    () => api.get(`/worker/dashboard/?week=${encodeURIComponent(week)}`),
    [week],
  )

  // Keep the previous view on screen while a different week loads, so the
  // filter never blanks the dashboard between selections.
  if (loading && !data) return <Loading label={t('dashboard.loadingDashboard')} />
  if (error && !data) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const weeks = data.weeks ?? []
  const period = data.period
  const allWeeks = period?.is_all_weeks ?? true

  const followupSummary = data.followup_summary
  const followupCounts = followupSummary?.counts
  const followupPatients = followupSummary?.patients ?? []
  // The dropdown lists only patients who appear in the list above it, so a
  // selection can never reach a record this worker may not open. If a chosen
  // patient has nothing due in a newly selected week, the filter falls back to
  // all patients rather than leaving the dropdown out of step with the list.
  const selectedPatient = followupPatients.some(
    (option) => String(option.id) === followupPatient,
  )
    ? followupPatient
    : ALL_PATIENTS
  const visibleFollowups = (data.pending_followups ?? []).filter(
    (followup) =>
      selectedPatient === ALL_PATIENTS ||
      String(followup.patient) === selectedPatient,
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {t('dashboard.pageTitle')}
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {data.village
              ? `${data.village.name} · ${data.village.cluster}`
              : t('shared.noVillageAssigned')}
            {period?.range_label ? (
              <span className="text-ink-400">
                {' '}
                · {allWeeks ? t('dashboard.allWeeks') : period.label} · {period.range_label}
              </span>
            ) : null}
          </p>
        </div>

        {weeks.length > 0 && (
          <div className="ml-auto">
            <label className="label" htmlFor="week-filter">
              {t('dashboard.timePeriod')}
            </label>
            <select
              id="week-filter"
              className="input w-auto min-w-[13rem]"
              value={week}
              onChange={(event) => setWeek(event.target.value)}
              disabled={loading}
            >
              <option value={ALL_WEEKS}>{t('dashboard.allWeeks')}</option>
              {weeks.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label} · {option.range_label}
                  {option.is_current_week ? ` (${t('dashboard.thisWeek')})` : ''}
                </option>
              ))}
            </select>
          </div>
        )}

        <Link
          to="/worker/assessment/new"
          className={`btn-care ${weeks.length > 0 ? '' : 'ml-auto'}`}
        >
          {t('dashboard.newPatientAssessment')}
        </Link>
      </div>

      {error && (
        <ErrorNote message={error} onRetry={reload} />
      )}

      {period?.notice && (
        <p className="rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-600">
          {period.notice}
        </p>
      )}

      {!allWeeks && !period.has_activity && (
        <p className="rounded-md border border-ink-200 bg-white px-3 py-2 text-sm text-ink-600">
          {period.empty_message || t('dashboard.noActivityThisWeek')}
        </p>
      )}

      <RealWorldCommunityProfile profile={data.village?.real_world_profile ?? null} />
      <CommunityMap profile={data.village?.real_world_profile ?? null} />

      {allWeeks ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat value={data.today.assessment_count} label={t('dashboard.assessmentsToday')} tone="care" />
          <Stat
            value={data.today.concerning_count}
            label={t('dashboard.concerningToday')}
            tone="amber"
          />
          <Stat value={data.today.urgent_count} label={t('dashboard.urgentToday')} tone="red" />
          <Stat value={data.pending_followup_count} label={t('dashboard.pendingFollowups')} />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            value={period.assessment_count}
            label={t('dashboard.assessmentsPeriod', { period: period.label })}
            tone="care"
          />
          <Stat
            value={period.concerning_count}
            label={t('dashboard.concerningThisWeek')}
            tone="amber"
          />
          <Stat value={period.urgent_count} label={t('dashboard.urgentThisWeek')} tone="red" />
          <Stat
            value={period.followup_count}
            label={t('dashboard.followupsDueThisWeek')}
          />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3 items-start">
        <Card
          title={allWeeks ? t('dashboard.recentAssessments') : t('dashboard.assessmentsPeriodTitle', { period: period.label })}
          className="lg:col-span-2"
        >
          {data.recent_assessments.length === 0 ? (
            <Empty>
              {allWeeks
                ? t('dashboard.noAssessmentsYet')
                : t('dashboard.noAssessmentsThisWeek')}
            </Empty>
          ) : (
            <div className="overflow-x-auto -mx-5">
              <table className="w-full min-w-[560px]">
                <thead>
                  <tr>
                    <th className="table-head">{t('dashboard.tablePatient')}</th>
                    <th className="table-head">{t('dashboard.tableSymptoms')}</th>
                    <th className="table-head">{t('dashboard.tableTriage')}</th>
                    <th className="table-head">{t('dashboard.tableDate')}</th>
                    <th className="table-head">{t('dashboard.tableAggregated')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_assessments.map((assessment) => (
                    <tr key={assessment.id} className="hover:bg-ink-50">
                      <td className="table-cell">
                        <Link
                          to={`/worker/patient/${assessment.patient}`}
                          className="font-medium text-care-700 hover:underline"
                        >
                          {assessment.patient_code}
                        </Link>
                        <div className="text-xs text-ink-400">
                          {assessment.patient_name}
                        </div>
                      </td>
                      <td className="table-cell text-ink-600">
                        {[
                          ...assessment.symptoms,
                          ...(assessment.other_symptom_text ? ['other'] : []),
                        ]
                          .join(', ')
                          .replace(/_/g, ' ') || '—'}
                        <div className="text-xs text-ink-400">
                          {t('dashboard.dayCount', { count: assessment.duration_days })}
                        </div>
                      </td>
                      <td className="table-cell">
                        <TriagePill level={assessment.triage_level} />
                        {assessment.escalation_forced && (
                          <div className="text-xs text-red-600 mt-1">
                            {t('dashboard.escalationForced')}
                          </div>
                        )}
                      </td>
                      <td className="table-cell text-ink-600">
                        {assessment.encounter_date}
                      </td>
                      <td className="table-cell">
                        {assessment.aggregated_at ? (
                          <span className="text-xs text-care-700">
                            {t('dashboard.countedAnonymously')}
                          </span>
                        ) : (
                          <span className="text-xs text-ink-400">{t('dashboard.pendingAggregation')}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <SymptomSummaryCard
          summary={data.symptom_summary}
          onCreateReport={() =>
            navigate('/worker/community-report', {
              state: {
                prefill: data.symptom_summary?.report_prefill ?? [],
                summary: data.symptom_summary,
              },
            })
          }
        />

        {/* Pending follow-ups — most urgent first, filterable by patient. */}
        <Card
          className="lg:col-span-3"
          title={
            allWeeks ? t('dashboard.pendingFollowupsTitle') : t('dashboard.followupsDueTitle', { period: period.label })
          }
          action={
            followupPatients.length > 0 ? (
              <select
                className="input w-auto min-w-[11rem] py-1 text-xs"
                value={selectedPatient}
                onChange={(event) => setFollowupPatient(event.target.value)}
                aria-label={t('dashboard.filterFollowupsAria')}
              >
                <option value={ALL_PATIENTS}>{t('dashboard.allPatients')}</option>
                {followupPatients.map((option) => (
                  <option key={option.id} value={String(option.id)}>
                    {option.patient_name || option.patient_code} (
                    {option.pending_count})
                  </option>
                ))}
              </select>
            ) : null
          }
        >
          {followupCounts && followupCounts.total > 0 && (
            <p className="mb-3 text-xs text-ink-600">
              <span
                className={
                  followupCounts.overdue ? 'font-semibold text-red-700' : ''
                }
              >
                {t('dashboard.overdueCount', { count: followupCounts.overdue })}
              </span>
              {' · '}
              <span
                className={
                  followupCounts.due_today ? 'font-semibold text-amber-700' : ''
                }
              >
                {t('dashboard.dueTodayCount', { count: followupCounts.due_today })}
              </span>
              {` · ${t('dashboard.upcomingCount', { count: followupCounts.upcoming })}`}
            </p>
          )}

          {visibleFollowups.length === 0 ? (
            <Empty>
              {selectedPatient !== ALL_PATIENTS
                ? t('dashboard.noFollowupsForPatient')
                : followupSummary?.empty_message ||
                  (allWeeks
                    ? t('dashboard.noPendingFollowups')
                    : t('dashboard.noFollowupsThisWeek'))}
            </Empty>
          ) : (
            <ol className="space-y-2">
              {visibleFollowups.map((followup, index) => (
                <li key={followup.id}>
                  <Link
                    to={`/worker/patient/${followup.patient}`}
                    className={`flex flex-wrap items-center gap-3 rounded-md border px-3 py-2 transition-colors hover:bg-ink-50 ${
                      followup.followup_status === 'OVERDUE'
                        ? 'border-red-200'
                        : followup.followup_status === 'DUE_TODAY'
                          ? 'border-amber-200'
                          : 'border-ink-200'
                    }`}
                  >
                    <span className="w-5 shrink-0 text-xs font-medium text-ink-400 tabular-nums">
                      {index + 1}.
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-ink-800">
                        {followup.patient_name || followup.patient_code}
                      </span>
                      <span className="block text-xs text-ink-400">
                        {followup.patient_code}
                      </span>
                    </span>
                    <span className="ml-auto text-right">
                      <span className="block font-mono text-xs text-ink-600">
                        {followup.due_date || '—'}
                      </span>
                      <span className="block text-xs text-ink-400">
                        {followup.due_description}
                      </span>
                    </span>
                    <FollowUpPill status={followup.followup_status} />
                  </Link>
                  {followup.notes && (
                    <p className="mt-1 pl-8 text-xs text-ink-600">
                      {followup.notes}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}

          {followupSummary?.overdue_outside_message && (
            <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {followupSummary.overdue_outside_message}
            </p>
          )}
          {followupSummary?.truncated_message && (
            <p className="mt-3 text-xs text-ink-400">
              {followupSummary.truncated_message}
            </p>
          )}
          <p className="mt-3 border-t border-ink-200 pt-3 text-xs text-ink-400">
            {t('dashboard.selectPatientHint')}
          </p>
        </Card>
      </div>

      <PregnancySummaryCard />
    </div>
  )
}
