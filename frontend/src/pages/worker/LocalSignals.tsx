import { useState } from 'react'

import { Card, Delta, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { LocalSignals } from '@/types'

export default function LocalSignalsPage() {
  const { data, loading, error, reload } = useAsync<LocalSignals>(() =>
    api.get('/local-signals/'),
  )
  const [openCategory, setOpenCategory] = useState<string | null>(null)

  if (loading) return <Loading label="Loading local signals…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const groups = data.grouped ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Local signals</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data.village
            ? `${data.village.name} · ${data.village.cluster}`
            : 'No village assigned'}
        </p>
        <p className="text-xs text-ink-400 mt-2 max-w-2xl">
          Aggregated signals reported for your own village only — not
          individual diagnoses or confirmed disease cases. A category shown
          as above baseline means recent reported counts are higher than that
          source&apos;s own recent average, which may be worth a closer look.
          Use this to help notice unusual local patterns and decide whether
          further review or reporting is needed.
        </p>
      </div>

      <div
        className={`rounded-lg border px-4 py-3 ${
          data.rising_categories?.length
            ? 'border-amber-300 bg-amber-50'
            : 'border-care-200 bg-care-50'
        }`}
      >
        <p
          className={`text-sm ${
            data.rising_categories?.length ? 'text-amber-900' : 'text-care-700'
          }`}
        >
          {data.headline}
        </p>
      </div>

      <Card title={`Reported signals by category (${groups.length})`}>
        {groups.length === 0 ? (
          <Empty>No signals recorded for your area yet.</Empty>
        ) : (
          <ul className="space-y-2">
            {groups.map((group) => {
              const open = openCategory === group.category
              return (
                <li
                  key={group.category}
                  className={`rounded-md border ${
                    group.is_rising
                      ? 'border-amber-300 bg-amber-50/40'
                      : 'border-ink-200'
                  }`}
                >
                  <button
                    className="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-ink-50/60"
                    onClick={() => setOpenCategory(open ? null : group.category)}
                    aria-expanded={open}
                  >
                    <span
                      className={`h-2 w-2 rounded-full shrink-0 ${
                        group.is_rising ? 'bg-amber-500' : 'bg-ink-200'
                      }`}
                    />
                    <span className="text-sm font-medium flex-1 min-w-0">
                      {group.label}
                    </span>
                    {group.is_rising && (
                      <span className="pill bg-amber-100 text-amber-800">
                        above baseline
                      </span>
                    )}
                    <span className="text-xs text-ink-400">
                      {group.signals.length} record
                      {group.signals.length === 1 ? '' : 's'}
                    </span>
                    <span className="text-ink-400 text-xs">
                      {open ? '▾' : '▸'}
                    </span>
                  </button>

                  {open && (
                    <div className="border-t border-ink-200 overflow-x-auto">
                      <table className="w-full min-w-[520px]">
                        <thead>
                          <tr>
                            <th className="table-head">Source</th>
                            <th className="table-head">Week</th>
                            <th className="table-head">Baseline</th>
                            <th className="table-head">Reported</th>
                            <th className="table-head">Change</th>
                          </tr>
                        </thead>
                        <tbody>
                          {group.signals.map((signal) => (
                            <tr key={signal.id}>
                              <td className="table-cell font-medium">
                                {signal.source_kind}
                              </td>
                              <td className="table-cell font-mono text-xs">
                                {signal.week_label}
                              </td>
                              <td className="table-cell font-mono">
                                {signal.baseline ?? '—'}
                              </td>
                              <td className="table-cell font-mono">
                                {signal.is_reported ? (
                                  `${signal.value} ${signal.unit}`
                                ) : (
                                  <span className="text-ink-400 italic">
                                    not submitted
                                  </span>
                                )}
                              </td>
                              <td className="table-cell">
                                <Delta value={signal.change_pct} />
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        <div className="mt-4 border-t border-ink-200 pt-3 space-y-1">
          <p className="text-xs text-ink-600">{data.signal_note}</p>
          <p className="text-xs text-ink-400">
            {data.scope_note} A source that did not submit is shown as “not
            submitted” — never as zero.
          </p>
        </div>
      </Card>
    </div>
  )
}
