import { Link } from 'react-router-dom'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
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
import type { OfficerDashboard, TrendPoint } from '@/types'

const SERIES_COLOURS: Record<string, string> = {
  CHW: '#3b5bad',
  PHC: '#0e9f77',
  PHARMACY: '#c2691a',
  SCHOOL: '#8b5cf6',
  LAB: '#dc2626',
  WEATHER: '#64748b',
  RURALCARE_AGGREGATE: '#0891b2',
}

/**
 * Normalises each source to "percent of its own baseline" so streams measured
 * in different units (reports, units sold, % absent) can share one axis without
 * implying they are the same quantity.
 */
function buildChartData(trends: Record<string, TrendPoint[]>) {
  const byWeek = new Map<string, Record<string, number | string>>()

  for (const [kind, points] of Object.entries(trends)) {
    for (const point of points) {
      if (point.baseline == null || point.baseline === 0) continue
      const row = byWeek.get(point.week_label) ?? { week: point.week_label }
      const pct = Math.round((point.value / point.baseline) * 100)
      const existing = row[kind]
      row[kind] =
        typeof existing === 'number' ? Math.max(existing, pct) : pct
      byWeek.set(point.week_label, row)
    }
  }

  return [...byWeek.values()].sort((a, b) =>
    String(a.week).localeCompare(String(b.week)),
  )
}

export default function OfficerDashboardPage() {
  const { data, loading, error, reload } = useAsync<OfficerDashboard>(() =>
    api.get('/officer/dashboard/'),
  )

  if (loading) return <Loading label="Loading community intelligence…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const chartData = buildChartData(data.trends)
  const seriesKeys = Object.keys(data.trends).filter((k) => k !== 'WEATHER')

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            Community intelligence
          </h1>
          <p className="text-sm text-ink-600 mt-0.5">
            {data.scope?.is_district_wide
              ? `${data.district || 'District'} — all villages`
              : `${data.scope?.village_name ?? ''} · ${data.district}`}
          </p>
        </div>
        <button className="btn-ghost ml-auto" onClick={reload}>
          Refresh
        </button>
      </div>

      {data.new_reports > 0 && (
        <Link
          to="/officer/community-reports"
          className="flex items-center gap-3 rounded-lg border border-sentinel-300 bg-sentinel-50 px-4 py-3 hover:bg-sentinel-100/60 transition-colors"
        >
          <span className="pill bg-sentinel-600 text-white">
            {data.new_reports} new
          </span>
          <span className="text-sm text-sentinel-900">
            {data.new_reports === 1
              ? 'A new community report has been submitted by a worker in your area.'
              : `${data.new_reports} new community reports have been submitted by workers in your area.`}
          </span>
          <span className="ml-auto text-sm text-sentinel-700">Review →</span>
        </Link>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <Stat
          value={data.summary.active_alerts}
          label="Active alerts"
          tone="sentinel"
        />
        <Stat
          value={data.summary.high_severity}
          label="High severity"
          tone="red"
        />
        <Stat
          value={data.summary.under_investigation}
          label="Under investigation"
          tone="amber"
        />
        <Stat
          value={data.summary.villages_monitored}
          label="Villages monitored"
        />
        <Stat
          value={`${Math.round(data.summary.human_review_rate * 100)}%`}
          label="Alerts requiring human review"
          tone="care"
        />
      </div>

      <Card title="Community trends — each source against its own baseline">
        {chartData.length === 0 ? (
          <Empty>No trend data yet.</Empty>
        ) : (
          <>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={chartData}
                  margin={{ top: 8, right: 12, bottom: 4, left: -18 }}
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
                    unit="%"
                    domain={[0, 'auto']}
                  />
                  <Tooltip
                    formatter={(value: number, name: string) => [
                      `${value}% of baseline`,
                      name,
                    ]}
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 6,
                      border: '1px solid #dde1e9',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {seriesKeys.map((kind) => (
                    <Line
                      key={kind}
                      type="monotone"
                      dataKey={kind}
                      stroke={SERIES_COLOURS[kind] ?? '#8a94a6'}
                      strokeWidth={2}
                      dot={{ r: 2 }}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <p className="text-xs text-ink-400 mt-2">
              100% is each source's own recent baseline. Sources are measured in
              different units, so they are shown as a percentage of their own
              normal rather than on a shared absolute scale.
            </p>
          </>
        )}
      </Card>

      <Card
        title="Active alerts"
        action={
          <span className="text-xs text-ink-400">
            {data.outcomes.valid_signal} valid · {data.outcomes.false_alert}{' '}
            false · {data.outcomes.resolved} resolved
          </span>
        }
      >
        {data.alerts.length === 0 ? (
          <Empty>
            No active alerts. Nothing has met the corroboration threshold.
          </Empty>
        ) : (
          <ul className="space-y-3">
            {data.alerts.map((alert) => (
              <li key={alert.id}>
                <Link
                  to={`/officer/alerts/${alert.id}`}
                  className="block rounded-md border border-ink-200 p-4 hover:border-sentinel-500 hover:bg-sentinel-50/40 transition-colors"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityPill severity={alert.severity} />
                    <SafetyPill verdict={alert.safety_verdict} />
                    <span className="font-medium text-sm">{alert.title}</span>
                    <span className="ml-auto text-xs text-ink-400 font-mono">
                      {alert.week_label}
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-600">
                    <span>
                      <span className="font-semibold">
                        {alert.corroborating_source_count}
                      </span>{' '}
                      independent source(s)
                    </span>
                    <span>
                      Cross-level:{' '}
                      <span className="font-semibold">
                        {alert.cross_level_verdict.toLowerCase()}
                      </span>
                    </span>
                    <span>
                      Confidence:{' '}
                      <span className="font-mono">
                        {alert.confidence.toFixed(2)}
                      </span>
                    </span>
                    <span className="text-ink-400">
                      {alert.status.replace(/_/g, ' ').toLowerCase()}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        <p className="text-xs text-ink-400 mt-4 border-t border-ink-200 pt-3">
          Every alert is a request for human attention with its evidence
          attached — never a conclusion, and never an outbreak declaration. No
          automated action has been taken.
        </p>
      </Card>
    </div>
  )
}
