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

import { SourceFreshnessPanel } from '@/components/SourceFreshness'
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
import type { OfficerDashboard, TrendDirection } from '@/types'

/** One colour per health-signal category line — same palette as the
 *  Community Data page's chart, so the two views read as one visual
 *  language rather than two different products. */
const SERIES_COLOURS = ['#3b5bad', '#0e9f77', '#c2691a', '#8b5cf6', '#dc2626']

const TREND_CHIP: Record<TrendDirection, { arrow: string; chip: string }> = {
  INCREASING: { arrow: '↑', chip: 'bg-red-100 text-red-700' },
  DECREASING: { arrow: '↓', chip: 'bg-care-100 text-care-700' },
  STABLE: { arrow: '→', chip: 'bg-ink-100 text-ink-600' },
  INSUFFICIENT_DATA: { arrow: '–', chip: 'bg-ink-100 text-ink-400' },
}

export default function OfficerDashboardPage() {
  const { data, loading, error, reload } = useAsync<OfficerDashboard>(() =>
    api.get('/officer/dashboard/'),
  )

  if (loading) return <Loading label="Loading community intelligence…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const trend = data.community_trend

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

      {/* Placed above the alert list deliberately: how current the evidence is
          belongs before the conclusions drawn from it, not as a footnote. */}
      <Card
        title={`Source freshness${
          data.source_freshness_summary?.needs_attention
            ? ` — ${data.source_freshness_summary.needs_attention} need attention`
            : ''
        }`}
      >
        <SourceFreshnessPanel sources={data.source_freshness ?? []} />
      </Card>

      <Card title="Community reported signals over time">
        <p className="text-xs text-ink-600 -mt-1 mb-3">
          Actual signals recorded through Health Worker reports for your
          monitored community.
        </p>

        {trend.is_empty || trend.points.length === 0 ? (
          <>
            <Empty>
              {trend.empty_message || 'No community reports recorded for this period.'}
            </Empty>
            <p className="-mt-3 text-center text-xs text-ink-400">
              {trend.empty_hint}
            </p>
          </>
        ) : (
          <>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={trend.points}
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
                    allowDecimals={false}
                  />
                  <Tooltip
                    formatter={(value: number, name: string) => [
                      `${value} reported`,
                      name,
                    ]}
                    contentStyle={{
                      fontSize: 12,
                      borderRadius: 6,
                      border: '1px solid #dde1e9',
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  {trend.keys.map((key, index) => (
                    <Line
                      key={key}
                      type="monotone"
                      dataKey={key}
                      stroke={SERIES_COLOURS[index % SERIES_COLOURS.length]}
                      strokeWidth={2}
                      dot={{ r: 2 }}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-ink-200 pt-3">
              <span
                className={`pill ${
                  (TREND_CHIP[trend.trend.direction] ?? TREND_CHIP.INSUFFICIENT_DATA).chip
                }`}
              >
                {(TREND_CHIP[trend.trend.direction] ?? TREND_CHIP.INSUFFICIENT_DATA).arrow}{' '}
                {trend.trend.direction_label}
              </span>
              <span className="text-xs text-ink-600">{trend.trend_note}</span>
              <span className="ml-auto text-xs text-ink-400">
                {trend.total_reported} reported across {trend.weeks_covered} week
                {trend.weeks_covered === 1 ? '' : 's'}
              </span>
            </div>
            <p className="mt-2 text-xs text-ink-400">
              Reported counts, not confirmed diagnoses. Showing the busiest
              health signals for your monitored area.
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
