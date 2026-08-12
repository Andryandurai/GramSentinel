import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import {
  Card,
  Empty,
  ErrorNote,
  Loading,
  SafetyPill,
  SeverityPill,
  Stat,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { AdminOverview } from '@/types'

const ALL = 'all'

const SERIES_COLOURS = [
  '#3b5bad',
  '#0e9f77',
  '#c2691a',
  '#8b5cf6',
  '#dc2626',
  '#0891b2',
]

const STATUS_STYLES: Record<string, string> = {
  Normal: 'bg-care-100 text-care-700',
  Monitoring: 'bg-amber-100 text-amber-800',
  'Under investigation': 'bg-red-100 text-red-700',
}

const ACTIVITY_STYLES: Record<string, string> = {
  ASSESSMENT: 'bg-care-500',
  COMMUNITY_REPORT: 'bg-sentinel-500',
  ALERT: 'bg-red-500',
  INVESTIGATION: 'bg-amber-500',
  OUTCOME: 'bg-violet-500',
}

function relativeTime(value: string): string {
  const then = new Date(value).getTime()
  if (Number.isNaN(then)) return ''
  const minutes = Math.round((Date.now() - then) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export default function AdminDashboard() {
  const [village, setVillage] = useState<string>(ALL)
  const { data, loading, error, reload } = useAsync<AdminOverview>(
    () => api.get(`/admin/overview/?village=${encodeURIComponent(village)}`),
    [village],
  )

  // Village options come from the first successful load, so the selector does
  // not vanish while a subsequent filter is loading.
  const [options, setOptions] = useState<AdminOverview['villages']>([])
  if (data && data.villages.length && options.length === 0) {
    setOptions(data.villages)
  }

  const selector = (
    <div className="flex items-center gap-2">
      <label
        htmlFor="village-filter"
        className="text-sm font-medium text-ink-600"
      >
        Village
      </label>
      <select
        id="village-filter"
        className="input w-auto min-w-[11rem] py-1.5"
        value={village}
        onChange={(e) => setVillage(e.target.value)}
      >
        <option value={ALL}>All Villages</option>
        {(options.length ? options : (data?.villages ?? [])).map((option) => (
          <option key={option.code} value={option.code}>
            {option.label} — {option.name}
          </option>
        ))}
      </select>
    </div>
  )

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <div className="flex flex-wrap items-center gap-4">
          <h1 className="text-xl font-semibold tracking-tight">
            Platform overview
          </h1>
          <div className="ml-auto">{selector}</div>
        </div>
        <Loading label="Loading overview…" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        <h1 className="text-xl font-semibold tracking-tight">
          Platform overview
        </h1>
        <ErrorNote message={error} onRetry={reload} />
      </div>
    )
  }

  if (!data) return null

  const isAll = data.scope.mode === 'all'
  const { totals } = data

  return (
    <div className="space-y-6">
      {/* Scope header — the question "am I looking at all villages or one?"
          should be answerable without reading anything else. */}
      <div className="flex flex-wrap items-center gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Platform overview
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {isAll
              ? `All villages — ${data.scope.village_count} monitored areas combined`
              : `${data.scope.label} · ${data.scope.village?.name} · ${data.scope.village?.cluster}`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {selector}
          <button className="btn-ghost py-1.5" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>

      <div
        className={`rounded-lg border px-4 py-2.5 text-sm ${
          isAll
            ? 'border-sentinel-200 bg-sentinel-50 text-sentinel-900'
            : 'border-care-200 bg-care-50 text-care-800'
        }`}
      >
        <span className="font-semibold">
          {isAll ? 'Viewing: All Villages' : `Viewing: ${data.scope.label}`}
        </span>
        {!isAll && (
          <span className="ml-2 text-ink-600">
            Other villages are excluded from every figure below.
          </span>
        )}
      </div>

      {data.is_empty ? (
        <Card title="No activity">
          <Empty>
            No activity recorded for {isAll ? 'any village' : data.scope.label}{' '}
            yet.
          </Empty>
        </Card>
      ) : (
        <>
          {/* Platform statistics */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat value={totals.patients} label="Patients" />
            <Stat
              value={totals.assessments}
              label="Assessments"
              tone="care"
            />
            <Stat
              value={totals.community_reports}
              label="Community reports"
              tone="sentinel"
            />
            <Stat
              value={totals.reported_cases}
              label="Reported cases"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              value={totals.alerts_active}
              label="Active alerts"
              tone={totals.alerts_active ? 'amber' : 'ink'}
            />
            <Stat
              value={totals.alerts_under_investigation}
              label="Under investigation"
              tone={totals.alerts_under_investigation ? 'red' : 'ink'}
            />
            <Stat
              value={totals.alerts_resolved}
              label="Resolved alerts"
              tone="care"
            />
            <Stat
              value={`${totals.workers} / ${totals.officers}`}
              label="Workers / health officers"
            />
          </div>

          {/* Village comparison */}
          <Card
            title={isAll ? 'Village summary' : `${data.scope.label} summary`}
          >
            {data.village_summary.length === 0 ? (
              <Empty>No villages configured.</Empty>
            ) : (
              <div className="overflow-x-auto -mx-5">
                <table className="w-full min-w-[720px]">
                  <thead>
                    <tr>
                      <th className="table-head">Village</th>
                      <th className="table-head">Patients</th>
                      <th className="table-head">Assessments</th>
                      <th className="table-head">Reports</th>
                      <th className="table-head">Active alerts</th>
                      <th className="table-head">Resolved</th>
                      <th className="table-head">Team</th>
                      <th className="table-head">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.village_summary.map((row) => (
                      <tr key={row.code} className="hover:bg-ink-50">
                        <td className="table-cell">
                          <span className="font-medium">{row.label}</span>
                          <div className="text-xs text-ink-400">{row.name}</div>
                        </td>
                        <td className="table-cell font-mono">{row.patients}</td>
                        <td className="table-cell font-mono">
                          {row.assessments}
                        </td>
                        <td className="table-cell font-mono">
                          {row.community_reports}
                        </td>
                        <td className="table-cell font-mono">
                          {row.active_alerts}
                        </td>
                        <td className="table-cell font-mono">
                          {row.resolved_alerts}
                        </td>
                        <td className="table-cell text-xs text-ink-600">
                          {row.workers}w / {row.officers}o
                        </td>
                        <td className="table-cell">
                          <span
                            className={`pill ${
                              STATUS_STYLES[row.status] ??
                              'bg-ink-100 text-ink-600'
                            }`}
                          >
                            {row.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* Trend */}
          <Card
            title={
              isAll
                ? 'Reported cases per village, by week'
                : 'Reported cases by category, by week'
            }
          >
            {data.trend.points.length === 0 ? (
              <Empty>Not enough reporting history to draw a trend yet.</Empty>
            ) : (
              <>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={data.trend.points}
                      margin={{ top: 8, right: 12, bottom: 4, left: -20 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" />
                      <XAxis
                        dataKey="week"
                        tick={{ fontSize: 11, fill: '#8a94a6' }}
                        tickLine={false}
                        axisLine={{ stroke: '#dde1e9' }}
                      />
                      <YAxis
                        tick={{ fontSize: 11, fill: '#8a94a6' }}
                        tickLine={false}
                        axisLine={false}
                        allowDecimals={false}
                      />
                      <Tooltip
                        contentStyle={{
                          fontSize: 12,
                          borderRadius: 6,
                          border: '1px solid #dde1e9',
                        }}
                        formatter={(value: number, name: string) => [
                          `${value} reported`,
                          name,
                        ]}
                      />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      {data.trend.keys.map((key, index) => (
                        <Bar
                          key={key}
                          dataKey={key}
                          fill={SERIES_COLOURS[index % SERIES_COLOURS.length]}
                          radius={[2, 2, 0, 0]}
                        />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-2 text-xs text-ink-400">
                  {data.signal_note}
                </p>
              </>
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* Health signal categories */}
            <Card title="Community health signals by category">
              {data.signal_categories.length === 0 ? (
                <Empty>No community reports recorded for this scope.</Empty>
              ) : (
                <>
                  <ul className="space-y-1.5">
                    {data.signal_categories.map((row) => {
                      const max = data.signal_categories[0].reported_cases || 1
                      const width = Math.max(
                        4,
                        Math.round((row.reported_cases / max) * 100),
                      )
                      return (
                        <li key={row.category} className="flex items-center gap-3">
                          <span className="w-52 shrink-0 truncate text-sm text-ink-800">
                            {row.label}
                          </span>
                          <span className="h-4 flex-1 rounded bg-ink-100 overflow-hidden">
                            <span
                              className="block h-full rounded bg-sentinel-500"
                              style={{ width: `${width}%` }}
                            />
                          </span>
                          <span className="w-16 shrink-0 text-right font-mono text-sm">
                            {row.reported_cases}
                          </span>
                          {row.described > 0 && (
                            <span
                              className="pill bg-ink-100 text-ink-600"
                              title={`${row.described} entry(ies) include a written description`}
                            >
                              {row.described} noted
                            </span>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                  <p className="mt-3 border-t border-ink-200 pt-3 text-xs text-ink-400">
                    {data.signal_note}
                  </p>
                </>
              )}
            </Card>

            {/* Recent activity */}
            <Card title="Recent activity">
              {data.recent_activity.length === 0 ? (
                <Empty>
                  No activity recorded for{' '}
                  {isAll ? 'any village' : data.scope.label} yet.
                </Empty>
              ) : (
                <ul className="space-y-2 max-h-[22rem] overflow-y-auto">
                  {data.recent_activity.map((event, index) => (
                    <li
                      key={`${event.kind}-${event.at}-${index}`}
                      className="flex gap-3"
                    >
                      <span
                        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                          ACTIVITY_STYLES[event.kind] ?? 'bg-ink-400'
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-ink-800">
                          <span className="font-medium">
                            {event.village_label}
                          </span>{' '}
                          — {event.summary}
                        </p>
                        <p className="text-xs text-ink-400">
                          {relativeTime(event.at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          {/* Alerts */}
          <Card
            title={`Alerts (${data.alerts.length})`}
            action={
              <span className="text-xs text-ink-400">
                {totals.outcome_valid_signal} valid ·{' '}
                {totals.outcome_false_alert} false ·{' '}
                {totals.outcome_resolved} resolved
              </span>
            }
          >
            {data.alerts.length === 0 ? (
              <Empty>
                No alerts have been raised for{' '}
                {isAll ? 'any village' : data.scope.label}.
              </Empty>
            ) : (
              <div className="overflow-x-auto -mx-5">
                <table className="w-full min-w-[820px]">
                  <thead>
                    <tr>
                      <th className="table-head">Village</th>
                      <th className="table-head">Signal</th>
                      <th className="table-head">Severity</th>
                      <th className="table-head">Safety</th>
                      <th className="table-head">Evidence</th>
                      <th className="table-head">Status</th>
                      <th className="table-head">Outcome</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.alerts.map((alert) => (
                      <tr key={alert.id} className="hover:bg-ink-50">
                        <td className="table-cell font-medium">
                          {alert.village_label}
                        </td>
                        <td className="table-cell">
                          <div className="text-ink-800">
                            {alert.category_label}
                          </div>
                          <div className="text-xs text-ink-400 font-mono">
                            {alert.week_label}
                          </div>
                        </td>
                        <td className="table-cell">
                          <SeverityPill severity={alert.severity} />
                        </td>
                        <td className="table-cell">
                          <SafetyPill verdict={alert.safety_verdict} />
                        </td>
                        <td className="table-cell text-xs text-ink-600">
                          {alert.corroborating_source_count} source(s)
                          <div className="text-ink-400">
                            {alert.evidence_summary}
                          </div>
                        </td>
                        <td className="table-cell text-xs text-ink-600">
                          {alert.status.replace(/_/g, ' ').toLowerCase()}
                        </td>
                        <td className="table-cell">
                          {alert.outcome ? (
                            <span className="pill bg-ink-100 text-ink-600">
                              {alert.outcome.replace(/_/g, ' ').toLowerCase()}
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
            <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
              This is a read-only view. Investigating and closing alerts remains
              the health officer's workflow.
            </p>
          </Card>

          {/* Assigned staff */}
          <Card title="Assigned staff">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.team.map((row) => (
                <div
                  key={row.code}
                  className="rounded-md border border-ink-200 p-3"
                >
                  <div className="text-sm font-semibold">{row.label}</div>
                  <div className="text-xs text-ink-400">{row.name}</div>
                  <dl className="mt-2 space-y-1.5 text-sm">
                    <div>
                      <dt className="text-xs text-ink-400">
                        CHW / PHC Worker
                      </dt>
                      <dd>
                        {row.workers.length ? (
                          row.workers.map((w) => (
                            <div key={w.username} className="text-ink-800">
                              {w.name}
                              <span className="text-xs text-ink-400 ml-1 font-mono">
                                {w.username}
                              </span>
                            </div>
                          ))
                        ) : (
                          <span className="text-ink-400">Not assigned</span>
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs text-ink-400">Health Officer</dt>
                      <dd>
                        {row.officers.length ? (
                          row.officers.map((o) => (
                            <div key={o.username} className="text-ink-800">
                              {o.name}
                              <span className="text-xs text-ink-400 ml-1 font-mono">
                                {o.username}
                              </span>
                            </div>
                          ))
                        ) : (
                          <span className="text-ink-400">Not assigned</span>
                        )}
                      </dd>
                    </div>
                  </dl>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
