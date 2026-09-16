import { useState } from 'react'
import { useTranslation } from 'react-i18next'
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
import { RealWorldCommunityProfile } from '@/components/RealWorldCommunityProfile'
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
function changeText(row: CommunityDataCategory, newLabel: string): string {
  if (row.direction === 'INSUFFICIENT_DATA') return '—'
  if (row.is_new_activity) return newLabel
  if (row.change_pct === null || row.change_pct === undefined) return '—'
  const rounded = Math.round(row.change_pct)
  return `${rounded > 0 ? '+' : ''}${rounded}%`
}

function TrendCell({ row }: { row: CommunityDataCategory }) {
  const { t: tc } = useTranslation('common')
  const style = TREND_STYLES[row.direction]
  return (
    <span className={`inline-flex items-center gap-1.5 ${style.text}`}>
      <span className="text-base leading-none" aria-hidden="true">
        {style.arrow}
      </span>
      <span className="text-sm">
        {tc(`trend.${row.direction}`, { defaultValue: row.direction_label })}
      </span>
    </span>
  )
}

const ALL = 'ALL'

export default function CommunityDataPage() {
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
  const [days, setDays] = useState(14)
  const [severity, setSeverity] = useState(ALL)
  const [category, setCategory] = useState(ALL)
  const { data, loading, error, reload } = useAsync<OfficerCommunityData>(
    () =>
      api.get(
        `/officer/community-data/?period=${days}` +
          `&severity=${encodeURIComponent(severity)}` +
          `&category=${encodeURIComponent(category)}`,
      ),
    [days, severity, category],
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
          {t('communityData.periodOption', { days: option })}
        </button>
      ))}
    </div>
  )

  const header = (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">
          {t('communityData.title')}
        </h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data?.scope.is_district_wide
            ? t('shared.scopeAllVillages')
            : (data?.scope.village_name ?? t('shared.scopeYourArea'))}
        </p>
      </div>
      <div className="ml-auto">{periodSelector}</div>
    </div>
  )

  if (loading && !data) {
    return (
      <div className="space-y-6">
        {header}
        <Loading label={t('communityData.loading')} />
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

      <RealWorldCommunityProfile profile={data.scope.real_world_profile} />

      <p className="text-sm text-ink-600">
        {t('communityData.reportedRange', {
          start: period.current.start,
          end: period.current.end,
          days: period.days,
        })}
      </p>

      {data.is_empty ? (
        <Card title={t('communityData.title')}>
          <Empty>{t('communityData.empty')}</Empty>
          <p className="text-center text-xs text-ink-400 -mt-3">
            {t('communityData.emptyHint')}
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
              label={t('communityData.stats.increasing')}
              tone={summary.increasing ? 'red' : 'ink'}
            />
            <Stat
              value={
                <span className="flex items-baseline gap-2">
                  {summary.stable}
                  <span className="text-base text-ink-400">→</span>
                </span>
              }
              label={t('communityData.stats.stable')}
            />
            <Stat
              value={
                <span className="flex items-baseline gap-2">
                  {summary.decreasing}
                  <span className="text-base text-care-600">↓</span>
                </span>
              }
              label={t('communityData.stats.decreasing')}
              tone="care"
            />
            <Stat
              value={summary.total_current_cases}
              label={t('communityData.stats.casesThisPeriod')}
              tone="sentinel"
            />
          </div>

          {!period.has_previous_period_data && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              {t('communityData.noPreviousPeriodData', { days: period.days })}
            </div>
          )}

          {/* The table */}
          <Card title={t('communityData.table.title')}>
            <div className="overflow-x-auto -mx-5">
              <table className="w-full min-w-[640px]">
                <thead>
                  <tr>
                    <th className="table-head">{t('communityData.table.columns.signal')}</th>
                    <th className="table-head">{t('communityData.table.columns.current')}</th>
                    <th className="table-head">{t('communityData.table.columns.previous')}</th>
                    <th className="table-head">{t('communityData.table.columns.change')}</th>
                    <th className="table-head">{t('communityData.table.columns.trend')}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.categories.map((row) => (
                    <tr key={row.category} className="hover:bg-ink-50">
                      <td className="table-cell">
                        <span className="font-medium text-ink-800">
                          {tc(`category.${row.category}`, { defaultValue: row.label })}
                        </span>
                        {row.described_entries > 0 && (
                          <span className="ml-2 pill bg-ink-100 text-ink-600">
                            {t('communityData.table.noted', { count: row.described_entries })}
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
                          {changeText(row, t('communityData.table.new'))}
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

          {/* Chart — the two filters below narrow exactly this card. */}
          <Card
            title={data.series.title || t('communityData.chart.titleFallback')}
            action={
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="label mb-0.5" htmlFor="severity-filter">
                    {t('communityData.chart.severityLabel')}
                  </label>
                  <select
                    id="severity-filter"
                    className="input w-auto min-w-[9rem] py-1 text-xs"
                    value={severity}
                    onChange={(event) => setSeverity(event.target.value)}
                  >
                    {(data.filters?.severity.options ?? []).map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.value === 'ALL'
                          ? t('communityData.chart.allSeverities')
                          : tc(`status.${option.value}`, { defaultValue: option.label })}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label mb-0.5" htmlFor="signal-filter">
                    {t('communityData.chart.signalLabel')}
                  </label>
                  <select
                    id="signal-filter"
                    className="input w-auto min-w-[13rem] py-1 text-xs"
                    value={category}
                    onChange={(event) => setCategory(event.target.value)}
                  >
                    {(data.filters?.category.options ?? []).map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.value === ALL
                          ? t('communityData.chart.allCases')
                          : tc(`category.${option.value}`, { defaultValue: option.label })}
                        {option.value !== ALL && !option.has_data
                          ? t('communityData.chart.noReportsSuffix')
                          : ''}
                      </option>
                    ))}
                  </select>
                </div>
                {(severity !== ALL || category !== ALL) && (
                  <button
                    className="btn-ghost py-1 text-xs"
                    onClick={() => {
                      setSeverity(ALL)
                      setCategory(ALL)
                    }}
                  >
                    {t('communityData.chart.clear')}
                  </button>
                )}
              </div>
            }
          >
            {data.filters?.notice && (
              <p className="mb-3 rounded-md border border-ink-200 bg-ink-50 px-3 py-2 text-xs text-ink-600">
                {data.filters.notice}
              </p>
            )}

            {data.series.is_empty || data.series.points.length === 0 ? (
              <>
                <Empty>
                  {data.series.empty_message ||
                    t('communityData.chart.emptyFallback')}
                </Empty>
                <p className="-mt-3 text-center text-xs text-ink-400">
                  {data.series.empty_hint ||
                    t('communityData.chart.emptyHintFallback')}
                </p>
              </>
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
                        t('shared.reportedCount', { count: value }),
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

            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-ink-200 pt-3">
              {!data.series.is_empty && (
                <>
                  <span
                    className={`pill ${
                      (
                        TREND_STYLES[data.series.trend?.direction] ??
                        TREND_STYLES.INSUFFICIENT_DATA
                      ).chip
                    }`}
                  >
                    {
                      (
                        TREND_STYLES[data.series.trend?.direction] ??
                        TREND_STYLES.INSUFFICIENT_DATA
                      ).arrow
                    }{' '}
                    {data.series.trend
                      ? tc(`trend.${data.series.trend.direction}`, {
                          defaultValue: data.series.trend.direction_label,
                        })
                      : t('communityData.chart.insufficientData')}
                  </span>
                  <span className="text-xs text-ink-600">
                    {data.series.trend_note}
                  </span>
                  <span className="ml-auto text-xs text-ink-400">
                    {t('shared.trendSummary', {
                      total: data.series.total_reported,
                      count: data.series.weeks_covered,
                    })}
                  </span>
                </>
              )}
            </div>
          </Card>

          {/* Workers' own words */}
          {data.recent_observations.length > 0 && (
            <Card title={t('communityData.observations.title')}>
              <ul className="space-y-2">
                {data.recent_observations.map((observation, index) => (
                  <li
                    key={`${observation.category}-${observation.week_label}-${index}`}
                    className="rounded-md border border-ink-200 px-3 py-2"
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-medium">
                        {tc(`category.${observation.category}`, { defaultValue: observation.label })}
                      </span>
                      <span className="text-sm text-ink-600 font-mono">
                        {t('shared.reportedCount', { count: observation.case_count })}
                      </span>
                      {observation.unusual_observation && (
                        <span className="pill bg-amber-100 text-amber-800">
                          {t('shared.flaggedUnusual')}
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
        </>
      )}
    </div>
  )
}
