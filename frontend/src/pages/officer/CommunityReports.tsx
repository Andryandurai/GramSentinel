import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { OfficerCommunityReport } from '@/types'

interface Payload {
  reports: OfficerCommunityReport[]
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
  const { data, loading, error, reload } = useAsync<Payload>(() =>
    api.get('/officer/community-reports/'),
  )

  if (loading) return <Loading label="Loading community reports…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Community reports
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {data.scope.is_district_wide
              ? 'All villages in your district'
              : data.scope.village_name}
          </p>
        </div>
        <button className="btn-ghost ml-auto" onClick={reload}>
          Refresh
        </button>
      </div>

      <Card title={`Submitted reports (${data.reports.length})`}>
        {data.reports.length === 0 ? (
          <Empty>No community reports have been submitted for your area.</Empty>
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
                      New report
                    </span>
                  )}
                  <span className="text-sm font-semibold">
                    {report.village_name}
                  </span>
                  {report.unusual_observation && (
                    <span className="pill bg-amber-100 text-amber-800">
                      flagged unusual
                    </span>
                  )}
                  <span className="ml-auto text-xs text-ink-400 font-mono">
                    {report.week_label}
                  </span>
                </div>

                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-600">
                  <span>Reported by {report.worker_name}</span>
                  <span>{formatWhen(report.submitted_at)}</span>
                  <span>{report.total_cases} reported case(s) in total</span>
                </div>

                <ul className="mt-3 space-y-2">
                  {report.entries.map((entry) => (
                    <li
                      key={`${report.id}-${entry.category}-${entry.label}`}
                      className="rounded-md border border-ink-200 bg-white px-3 py-2"
                    >
                      <div className="flex items-baseline gap-2">
                        <span className="text-sm font-medium">
                          {entry.label}
                        </span>
                        <span className="text-sm text-ink-600 font-mono">
                          {entry.case_count} reported
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

                {report.notes && (
                  <p className="mt-3 text-sm text-ink-600 border-t border-ink-100 pt-2">
                    <span className="text-xs font-medium text-ink-400">
                      Worker notes:{' '}
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
