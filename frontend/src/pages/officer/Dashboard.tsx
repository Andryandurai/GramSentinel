import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
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
  Delta,
  Empty,
  ErrorNote,
  FreshnessPill,
  Loading,
  SafetyPill,
  SeverityPill,
  Stat,
} from '@/components/ui'
import { CommunityMap } from '@/components/CommunityMap'
import { RealWorldCommunityProfile } from '@/components/RealWorldCommunityProfile'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { LocalSignalReport, OfficerDashboard, TrendDirection } from '@/types'

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

/**
 * Shown once, when the dashboard first loads with an unread local signal
 * report waiting — a worker's own flag that a specific above-baseline
 * signal deserves attention, distinct from the active-alerts list below
 * (which is the system-generated, safety-gated GramSentinel signal).
 *
 * "View Report(s)" navigates to Community reports, whose own load already
 * marks these acknowledged (same rule the sibling community-report banner
 * below already relies on). "Dismiss" only closes this dialog — the report
 * stays unread and the persistent indicator further down the page still
 * shows it.
 */
function NewLocalSignalReportDialog({
  reports,
  count,
  onDismiss,
}: {
  reports: LocalSignalReport[]
  count: number
  onDismiss: () => void
}) {
  const navigate = useNavigate()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onDismiss()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onDismiss])

  const single = count === 1 ? reports[0] : null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 px-4"
      onClick={onDismiss}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-local-signal-heading"
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <span className="text-amber-600" aria-hidden="true">
            ⚠
          </span>
          <h2 id="new-local-signal-heading" className="text-base font-semibold text-ink-900">
            {count === 1 ? 'New local signal report' : `${count} new local signal reports`}
          </h2>
        </div>

        {single ? (
          <div className="mt-3 space-y-3 text-sm">
            <p className="text-ink-700">
              {single.village_name} Health Worker has reported an above-baseline local
              signal.
            </p>
            <dl className="rounded-md border border-ink-200 bg-ink-50 px-3 py-2 space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-ink-500">Signal</dt>
                <dd className="font-medium text-ink-800">{single.label}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Reported</dt>
                <dd className="font-mono text-ink-800">
                  {single.value} {single.unit}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Baseline</dt>
                <dd className="font-mono text-ink-800">{single.baseline ?? '—'}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-500">Change</dt>
                <dd>
                  <Delta value={single.change_pct} />
                </dd>
              </div>
            </dl>
          </div>
        ) : (
          <ul className="mt-3 space-y-1.5 text-sm">
            {reports.map((report) => (
              <li
                key={report.id}
                className="flex items-center justify-between gap-3 rounded-md border border-ink-200 px-3 py-1.5"
              >
                <span className="text-ink-700 min-w-0 truncate">
                  {report.label} · {report.village_name}
                </span>
                <Delta value={report.change_pct} />
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 flex gap-2">
          <button
            className="btn-care flex-1"
            onClick={() => {
              onDismiss()
              navigate('/officer/community-reports')
            }}
          >
            {count === 1 ? 'View Report' : 'View Reports'}
          </button>
          <button className="btn-ghost" onClick={onDismiss}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  )
}

export default function OfficerDashboardPage() {
  const { data, loading, error, reload } = useAsync<OfficerDashboard>(() =>
    api.get('/officer/dashboard/'),
  )
  const [showSignalPopup, setShowSignalPopup] = useState(false)
  const popupShownRef = useRef(false)

  // Appears once per visit to this page, not on every manual Refresh —
  // opening the dashboard is the trigger, not a poll.
  useEffect(() => {
    if (data && !popupShownRef.current && data.new_local_signal_reports > 0) {
      setShowSignalPopup(true)
      popupShownRef.current = true
    }
  }, [data])

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

      {data.new_local_signal_reports > 0 && (
        <Link
          to="/officer/community-reports"
          className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 hover:bg-amber-100/60 transition-colors"
        >
          <span className="pill bg-amber-600 text-white">⚠ {data.new_local_signal_reports} new</span>
          <span className="text-sm text-amber-900">
            {data.new_local_signal_reports === 1
              ? 'New local signal report from a Health Worker in your area.'
              : `${data.new_local_signal_reports} new local signal reports from Health Workers in your area.`}
          </span>
          <span className="ml-auto text-sm text-amber-700">Review →</span>
        </Link>
      )}

      {showSignalPopup && (
        <NewLocalSignalReportDialog
          reports={data.recent_local_signal_reports}
          count={data.new_local_signal_reports}
          onDismiss={() => setShowSignalPopup(false)}
        />
      )}

      <RealWorldCommunityProfile profile={data.scope?.real_world_profile ?? null} />
      <CommunityMap profile={data.scope?.real_world_profile ?? null} />

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

      {data.source_freshness.length > 0 ? (
        <Card title="Source freshness">
          <p className="text-xs text-ink-600 -mt-1 mb-3">
            How recently each source last reported — a recent update does not
            by itself mean an alert is warranted, and an old one does not by
            itself mean the situation is unsafe.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.source_freshness.map((freshness) => (
              <div
                key={freshness.source_kind}
                className="flex items-center justify-between rounded-md border border-ink-200 px-3 py-2"
              >
                <span className="text-sm font-medium">{freshness.source_label}</span>
                <FreshnessPill freshness={freshness} />
              </div>
            ))}
          </div>
        </Card>
      ) : (
        data.source_freshness_note && (
          <p className="text-xs text-ink-400">{data.source_freshness_note}</p>
        )
      )}

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
      </Card>
    </div>
  )
}
