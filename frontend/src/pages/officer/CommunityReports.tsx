import { useTranslation } from 'react-i18next'

import { Card, Delta, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { LocalSignalReport, OfficerCommunityReport } from '@/types'

interface Payload {
  reports: OfficerCommunityReport[]
  local_signal_reports: LocalSignalReport[]
  scope: { village_name: string | null; is_district_wide: boolean }
  note: string
}

function formatWhen(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
}

/**
 * Observations reported by frontline workers in this officer's area.
 *
 * Reports arrive here whether or not they cleared the corroboration threshold
 * for an alert — a single described concern that no other source corroborates
 * still deserves a human's eyes, it just does not become an alert.
 */
export default function OfficerCommunityReports() {
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
  const { data, loading, error, reload } = useAsync<Payload>(() =>
    api.get('/officer/community-reports/'),
  )

  if (loading) return <Loading label={t('communityReports.loading')} />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {t('communityReports.title')}
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {data.scope.is_district_wide
              ? t('shared.scopeAllVillages')
              : data.scope.village_name}
          </p>
        </div>
        <button className="btn-ghost ml-auto" onClick={reload}>
          {t('shared.refresh')}
        </button>
      </div>

      <Card
        title={t('communityReports.highSignalCard.title', {
          count: data.local_signal_reports.length,
        })}
      >
        {data.local_signal_reports.length === 0 ? (
          <Empty>{t('communityReports.highSignalCard.empty')}</Empty>
        ) : (
          <ul className="space-y-3">
            {data.local_signal_reports.map((report) => (
              <li
                key={report.id}
                className={`rounded-lg border p-4 ${
                  report.acknowledged
                    ? 'border-ink-200'
                    : 'border-amber-300 bg-amber-50/40'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  {!report.acknowledged && (
                    <span className="pill bg-amber-600 text-white">{t('shared.newReportBadge')}</span>
                  )}
                  <span className="text-sm font-semibold">
                    {tc(`category.${report.category}`, { defaultValue: report.label })}
                  </span>
                  <span className="pill bg-amber-100 text-amber-800">
                    {t('communityReports.highSignalCard.aboveBaseline')}
                  </span>
                  <span className="ml-auto text-xs text-ink-400 font-mono">
                    {report.week_label}
                  </span>
                </div>

                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600">
                  <span>{report.village_name}</span>
                  <span>{t('shared.reportedBy', { name: report.worker_name })}</span>
                  <span>{formatWhen(report.created_at)}</span>
                </div>

                <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 rounded-md border border-ink-200 bg-white px-3 py-2 text-sm">
                  <span className="text-ink-600">
                    {t('communityReports.highSignalCard.fields.source')}{' '}
                    <span className="font-medium text-ink-800">
                      {tc(`sources.${report.source_kind}`, { defaultValue: report.source_label })}
                    </span>
                  </span>
                  <span className="text-ink-600">
                    {t('communityReports.highSignalCard.fields.baseline')}{' '}
                    <span className="font-mono">{report.baseline ?? '—'}</span>
                  </span>
                  <span className="text-ink-600">
                    {t('communityReports.highSignalCard.fields.reported')}{' '}
                    <span className="font-mono">
                      {report.value} {report.unit}
                    </span>
                  </span>
                  <span className="text-ink-600 flex items-center gap-1">
                    {t('communityReports.highSignalCard.fields.change')}{' '}
                    <Delta value={report.change_pct} />
                  </span>
                </div>

                {report.note && (
                  <p className="mt-3 text-sm text-ink-600 border-t border-ink-100 pt-2">
                    <span className="text-xs font-medium text-ink-400">
                      {t('shared.workerNote')}{' '}
                    </span>
                    “{report.note}”
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title={t('communityReports.submittedCard.title', { count: data.reports.length })}>
        {data.reports.length === 0 ? (
          <Empty>{t('communityReports.submittedCard.empty')}</Empty>
        ) : (
          <ul className="space-y-3">
            {data.reports.map((report) => (
              <li
                key={report.id}
                className={`rounded-lg border p-4 ${
                  report.acknowledged
                    ? 'border-ink-200'
                    : 'border-sentinel-300 bg-sentinel-50/40'
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  {!report.acknowledged && (
                    <span className="pill bg-sentinel-600 text-white">
                      {t('shared.newReportBadge')}
                    </span>
                  )}
                  <span className="text-sm font-semibold">
                    {report.village_name}
                  </span>
                  {report.report_type === 'PREGNANCY' ? (
                    <span className="pill bg-purple-100 text-purple-800">
                      {t('communityReports.reportType.pregnancy')}
                    </span>
                  ) : (
                    <span className="pill bg-ink-100 text-ink-600">
                      {t('communityReports.reportType.general')}
                    </span>
                  )}
                  {report.unusual_observation && (
                    <span className="pill bg-amber-100 text-amber-800">
                      {t('shared.flaggedUnusual')}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-ink-400 font-mono">
                    {report.week_label}
                  </span>
                </div>

                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600">
                  <span>{t('shared.reportedBy', { name: report.worker_name })}</span>
                  <span>{formatWhen(report.submitted_at)}</span>
                  {report.report_type !== 'PREGNANCY' && (
                    <span>
                      {t('communityReports.submittedCard.totalCases', {
                        count: report.total_cases,
                      })}
                    </span>
                  )}
                </div>

                {report.report_type === 'PREGNANCY' && report.pregnancy_detail ? (
                  <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-md border border-purple-200 bg-purple-50/40 px-3 py-2 text-sm">
                    <div className="col-span-2 flex justify-between">
                      <dt className="text-ink-500">
                        {t('communityReports.pregnancy.patientCode')}
                      </dt>
                      <dd className="font-mono font-medium text-ink-800">
                        {report.pregnancy_detail.patient_code || '—'}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-ink-500">
                        {t('communityReports.pregnancy.visitsCompleted')}
                      </dt>
                      <dd className="font-medium text-ink-800">
                        {report.pregnancy_detail.completed_visit_count}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-ink-500">
                        {t('communityReports.pregnancy.followUpRequired')}
                      </dt>
                      <dd className="font-medium text-ink-800">
                        {report.pregnancy_detail.follow_up_required
                          ? t('shared.yes')
                          : t('shared.no')}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-ink-500">
                        {t('communityReports.pregnancy.lastCheckup')}
                      </dt>
                      <dd className="font-medium text-ink-800">
                        {report.pregnancy_detail.last_checkup_date ?? '—'}
                      </dd>
                    </div>
                    <div className="flex justify-between">
                      <dt className="text-ink-500">
                        {t('communityReports.pregnancy.nextCheckup')}
                      </dt>
                      <dd className="font-medium text-ink-800">
                        {report.pregnancy_detail.next_checkup_date ?? '—'}
                      </dd>
                    </div>
                    <div className="col-span-2">
                      <dt className="text-xs font-medium text-ink-400">
                        {t('communityReports.pregnancy.reason')}
                      </dt>
                      <dd className="mt-0.5 text-ink-800">
                        {report.pregnancy_detail.reason}
                      </dd>
                    </div>
                    {report.pregnancy_detail.remarks && (
                      <div className="col-span-2">
                        <dt className="text-xs font-medium text-ink-400">
                          {t('shared.workerNotes')}
                        </dt>
                        <dd className="mt-0.5 text-ink-800">
                          {report.pregnancy_detail.remarks}
                        </dd>
                      </div>
                    )}
                  </dl>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {report.entries.map((entry) => (
                      <li
                        key={`${report.id}-${entry.category}-${entry.label}`}
                        className="rounded-md border border-ink-200 bg-white px-3 py-2"
                      >
                        <div className="flex items-baseline gap-2">
                          <span className="text-sm font-medium">
                            {tc(`category.${entry.category}`, { defaultValue: entry.label })}
                          </span>
                          <span className="text-sm text-ink-600 font-mono">
                            {t('shared.reportedCount', { count: entry.case_count })}
                          </span>
                        </div>
                        {entry.description && (
                          <p className="mt-1 text-sm text-ink-800">
                            “{entry.description}”
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}

                {report.report_type !== 'PREGNANCY' && report.notes && (
                  <p className="mt-3 text-sm text-ink-600 border-t border-ink-100 pt-2">
                    <span className="text-xs font-medium text-ink-400">
                      {t('shared.workerNotes')}{' '}
                    </span>
                    {report.notes}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
          {data.note}
        </p>
      </Card>
    </div>
  )
}
