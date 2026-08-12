import { useState } from 'react'
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

import { Card, Empty, ErrorNote, Loading, Stat } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type {
  CommunityDataCategory,
  OfficerCommunityData,
  TrendDirection,
} from '@/types'

const SERIES_COLOURS = [
  '#3b5bad',
  '#0e9f77',
  '#c2691a',
  '#8b5cf6',
  '#dc2626',
]

const TREND_STYLES: Record<
  TrendDirection,
  { arrow: string; text: string; chip: string }
> = {
  INCREASING: {
    arrow: '↑',
    text: 'text-red-700',
    chip: 'bg-red-100 text-red-700',
  },
  DECREASING: {
    arrow: '↓',
    text: 'text-care-700',
    chip: 'bg-care-100 text-care-700',
  },
  STABLE: {
    arrow: '→',
    text: 'text-ink-600',
    chip: 'bg-ink-100 text-ink-600',
  },
  INSUFFICIENT_DATA: {
    arrow: '–',
    text: 'text-ink-400',
    chip: 'bg-ink-100 text-ink-400',
  },
}

/** Percentage, "new", or a dash — never NaN, Infinity or undefined. */
function changeText(row: CommunityDataCategory): string {
  if (row.direction === 'INSUFFICIENT_DATA') return '—'
  if (row.is_new_activity) return 'new'
  if (row.change_pct === null || row.change_pct === undefined) return '—'
  const rounded = Math.round(row.change_pct)
  return `${rounded > 0 ? '+' : ''}${rounded}%`
}

function TrendCell({ row }: { row: CommunityDataCategory }) {
  const style = TREND_STYLES[row.direction]
  return (
    <span className={`inline-flex items-center gap-1.5 ${style.text}`}>
      <span className="text-base leading-none" aria-hidden="true">
        {style.arrow}
      </span>
      <span className="text-sm">{row.direction_label}</span>
    </span>
  )
}

export default function CommunityDataPage() {
  const [days, setDays] = useState(14)
  const { data, loading, error, reload } = useAsync<OfficerCommunityData>(
    () => api.get(`/officer/community-data/?period=${days}`),
    [days],
  )

  const periodSelector = (
    <div className="flex items-center gap-1 rounded-md border border-ink-200 bg-white p-0.5">
      {[7, 14, 21].map((option) => (
        <button
          key={option}
          onClick={() => setDays(option)}
          className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
            days === option
              ? 'bg-sentinel-600 text-white'
              : 'text-ink-600 hover:bg-ink-50'
          }`}
        >
          Last {option} days
        </button>
      ))}
    </div>
  )

  const header = (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          Community health data
        </h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data?.scope.is_district_wide
            ? 'All villages in your district'
            : (data?.scope.village_name ?? 'Your area')}
        </p>
      </div>
      <div className="ml-auto">{periodSelector}</div>
    </div>
  )

  if (loading && !data) {
    return (
      <div className="space-y-6">
        {header}
        <Loading label="Loading community data…" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="space-y-6">
        {header}
        <ErrorNote message={error} onRetry={reload} />
      </div>
    )
  }

  if (!data) return null

  const { summary, period } = data

  return (
    <div className="space-y-6">
      {header}

      <p className="text-sm text-ink-600">
        Reported {period.current.start} to {period.current.end}, compared with
        the {period.days} days before it.
      </p>

      {data.is_empty ? (
        <Card title="Community health data">
          <Empty>No community data available for this period.</Empty>
          <p className="text-center text-xs text-ink-400 -mt-3">
            Try a longer period, or wait for the next community report from
            your area.
          </p>
        </Card>
      ) : (
        <>
          {/* At-a-glance counts */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              value={
                <span className="flex items-baseline gap-2">
                  {summary.increasing}
                  <span className="text-base text-red-600">↑</span>
                </span>
              }
              label="Signals increasing"
              tone={summary.increasing ? 'red' : 'ink'}
            />
            <Stat
              value={
                <span className="flex items-baseline gap-2">
                  {summary.stable}
                  <span className="text-base text-ink-400">→</span>
                </span>
              }
              label="Signals stable"
            />
            <Stat
              value={
                <span className="flex items-baseline gap-2">
                  {summary.decreasing}
                  <span className="text-base text-care-600">↓</span>
                </span>
              }
              label="Signals decreasing"
              tone="care"
            />
            <Stat
              value={summary.total_current_cases}
              label="Reported cases this period"
              tone="sentinel"
            />
          </div>

          {!period.has_previous_period_data && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              No reports exist for the previous {period.days} days, so trends
              cannot be calculated for this period yet.
            </div>
          )}

          {/* The table */}
          <Card title="Reported community health signals">
            <div className="overflow-x-auto -mx-5">
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr>
                    <th className="table-head">Health signal</th>
                    <th className="table-head">Current</th>
                    <th className="table-head">Previous</th>
                    <th className="table-head">Change</th>
                    <th className="table-head">Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {data.categories.map((row) => (
                    <tr key={row.category} className="hover:bg-ink-50">
                      <td className="table-cell">
                        <span className="font-medium text-ink-800">
                          {row.label}
                        </span>
                        {row.described_entries > 0 && (
                          <span className="ml-2 pill bg-ink-100 text-ink-600">
                            {row.described_entries} noted
                          </span>
                        )}
                      </td>
                      <td className="table-cell font-mono">
                        {row.current}
                      </td>
                      <td className="table-cell font-mono text-ink-600">
                        {row.previous === null ? '—' : row.previous}
                      </td>
                      <td className="table-cell">
                        <span
                          className={`font-mono text-sm ${TREND_STYLES[row.direction].text}`}
                        >
                          {changeText(row)}
                        </span>
                      </td>
                      <td className="table-cell">
                        <TrendCell row={row} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
              {data.note}
            </p>
          </Card>

          {/* Chart */}
          <Card title="Reported cases over time">
            {data.series.points.length === 0 ? (
              <Empty>Not enough reporting history to draw a trend yet.</Empty>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data.series.points}
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
                    {data.series.keys.map((key, index) => (
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
            )}
          </Card>

          {/* Workers' own words */}
          {data.recent_observations.length > 0 && (
            <Card title="Observations from your workers">
              <ul className="space-y-2">
                {data.recent_observations.map((observation, index) => (
                  <li
                    key={`${observation.category}-${observation.week_label}-${index}`}
                    className="rounded-md border border-ink-200 px-3 py-2"
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-medium">
                        {observation.label}
                      </span>
                      <span className="text-sm text-ink-600 font-mono">
                        {observation.case_count} reported
                      </span>
                      {observation.unusual_observation && (
                        <span className="pill bg-amber-100 text-amber-800">
                          flagged unusual
                        </span>
                      )}
                      <span className="ml-auto text-xs text-ink-400 font-mono">
                        {observation.week_label}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-ink-800">
                      “{observation.description}”
                    </p>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {observation.worker_name} · {observation.village_name}
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* How this relates to alerts */}
          <div className="rounded-lg border border-sentinel-200 bg-sentinel-50 px-4 py-3">
            <div className="text-sm font-semibold text-sentinel-700">
              Community data and alerts
            </div>
            <p className="mt-1 text-sm text-sentinel-900">
              {data.relationship_note}
            </p>
          </div>
        </>
      )}
    </div>
  )
}
