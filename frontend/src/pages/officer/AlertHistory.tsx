import { Link } from 'react-router-dom'

import {
  Card,
  Empty,
  ErrorNote,
  Loading,
  SafetyPill,
  SeverityPill,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { AlertSummary } from '@/types'

const OUTCOME_STYLES: Record<string, string> = {
  VALID_SIGNAL: 'bg-care-100 text-care-700',
  FALSE_ALERT: 'bg-amber-100 text-amber-800',
  RESOLVED: 'bg-ink-100 text-ink-600',
}

export default function AlertHistory() {
  const { data, loading, error, reload } = useAsync<AlertSummary[]>(() =>
    api.get('/alerts/'),
  )

  if (loading) return <Loading label="Loading alert history…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />

  const alerts = data ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Alert history</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          Past alerts with their recorded investigation outcomes — the basis for
          evaluating thresholds honestly.
        </p>
      </div>

      <Card title={`All alerts (${alerts.length})`}>
        {alerts.length === 0 ? (
          <Empty>No alerts have been raised yet.</Empty>
        ) : (
          <div className="overflow-x-auto -mx-5">
            <table className="w-full min-w-[760px]">
              <thead>
                <tr>
                  <th className="table-head">Alert</th>
                  <th className="table-head">Week</th>
                  <th className="table-head">Severity</th>
                  <th className="table-head">Safety</th>
                  <th className="table-head">Sources</th>
                  <th className="table-head">Status</th>
                  <th className="table-head">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((alert) => (
                  <tr key={alert.id} className="hover:bg-ink-50">
                    <td className="table-cell">
                      <Link
                        to={`/officer/alerts/${alert.id}`}
                        className="font-medium text-sentinel-700 hover:underline"
                      >
                        {alert.title}
                      </Link>
                      <div className="text-xs text-ink-400">
                        {alert.cluster}
                      </div>
                    </td>
                    <td className="table-cell font-mono text-xs">
                      {alert.week_label}
                    </td>
                    <td className="table-cell">
                      <SeverityPill severity={alert.severity} />
                    </td>
                    <td className="table-cell">
                      <SafetyPill verdict={alert.safety_verdict} />
                    </td>
                    <td className="table-cell font-mono">
                      {alert.corroborating_source_count}
                    </td>
                    <td className="table-cell text-ink-600 text-xs">
                      {alert.status.replace(/_/g, ' ').toLowerCase()}
                    </td>
                    <td className="table-cell">
                      {alert.outcome ? (
                        <span
                          className={`pill ${OUTCOME_STYLES[alert.outcome]}`}
                        >
                          {alert.outcome.replace(/_/g, ' ')}
                        </span>
                      ) : (
                        <span className="text-xs text-ink-400">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-ink-400 mt-4 border-t border-ink-200 pt-3">
          “Valid signal” means a human confirmed the alert was worth raising. It
          does not mean the system diagnosed a disease, confirmed an outbreak,
          or identified a pathogen.
        </p>
      </Card>
    </div>
  )
}
