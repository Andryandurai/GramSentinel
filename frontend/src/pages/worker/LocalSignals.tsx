import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, Delta, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type { LocalSignalRow, LocalSignals } from '@/types'

/** A signal reads as "above baseline" at this change — matches the
 *  backend's own `RISING_CHANGE_PCT_THRESHOLD`, so the button only ever
 *  appears for, and only ever succeeds for, a signal already shown that way. */
const RISING_THRESHOLD = 30

function isAboveBaseline(signal: LocalSignalRow): boolean {
  return signal.is_reported && signal.change_pct !== null && signal.change_pct >= RISING_THRESHOLD
}

interface ReportTarget {
  signal: LocalSignalRow
  categoryLabel: string
}

/** Confirmation dialog for "Report to Health Officer" — same dependency-free
 *  overlay style used elsewhere in this app (no shared modal component
 *  exists to reuse): closeable by Cancel, a backdrop click, or Escape. */
function ReportToOfficerDialog({
  target,
  villageName,
  workerName,
  onCancel,
  onSent,
}: {
  target: ReportTarget
  villageName: string
  workerName: string
  onCancel: () => void
  onSent: () => void
}) {
  const { t } = useTranslation('worker')
  const { t: tc } = useTranslation('common')
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { signal, categoryLabel } = target

  async function send() {
    setSending(true)
    setError(null)
    try {
      await api.post('/local-signal-reports/', { signal: signal.id, note: note.trim() })
      onSent()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('localSignals.sendError'))
      setSending(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 px-4"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="report-to-officer-heading"
        className="max-h-[85vh] w-full max-w-md overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="report-to-officer-heading" className="text-base font-semibold text-ink-900">
          {t('localSignals.reportToOfficer')}
        </h2>
        <p className="mt-1 text-xs text-ink-500">{t('localSignals.confirmTitle')}</p>

        <dl className="mt-3 space-y-2 text-sm">
          <div>
            <dt className="label">{t('localSignals.signal')}</dt>
            <dd className="text-ink-800">{categoryLabel}</dd>
          </div>
          <div>
            <dt className="label">{t('localSignals.statusLabel')}</dt>
            <dd>
              <span className="pill bg-amber-100 text-amber-800">{t('localSignals.aboveBaseline')}</span>
            </dd>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <dt className="label">{t('localSignals.source')}</dt>
              <dd className="text-ink-800">{signal.source_kind}</dd>
            </div>
            <div>
              <dt className="label">{t('localSignals.reportingWeek')}</dt>
              <dd className="font-mono text-xs text-ink-800">{signal.week_label}</dd>
            </div>
            <div>
              <dt className="label">{t('localSignals.baseline')}</dt>
              <dd className="font-mono text-ink-800">{signal.baseline ?? '—'}</dd>
            </div>
            <div>
              <dt className="label">{t('localSignals.reported')}</dt>
              <dd className="font-mono text-ink-800">
                {signal.value} {signal.unit}
              </dd>
            </div>
          </div>
          <div>
            <dt className="label">{t('localSignals.change')}</dt>
            <dd>
              <Delta value={signal.change_pct} />
            </dd>
          </div>
          <div className="rounded-md bg-ink-50 border border-ink-200 px-3 py-2">
            <dt className="label">{t('localSignals.destination')}</dt>
            <dd className="text-ink-800">
              {tc('role.HEALTH_OFFICER')} <span className="text-ink-400">·</span> {villageName}
            </dd>
            <dd className="mt-0.5 text-xs text-ink-400">
              {t('localSignals.reportedBy', { workerName })}
            </dd>
          </div>
        </dl>

        <div className="mt-4">
          <label className="label" htmlFor="report-note">
            {t('localSignals.optionalNote')}
          </label>
          <textarea
            id="report-note"
            rows={2}
            className="input"
            placeholder={t('localSignals.notePlaceholder')}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={1000}
          />
        </div>

        {error && (
          <div className="mt-3">
            <ErrorNote message={error} />
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button className="btn-care flex-1" onClick={send} disabled={sending}>
            {sending ? t('shared.sending') : t('localSignals.sendReport')}
          </button>
          <button className="btn-ghost" onClick={onCancel} disabled={sending}>
            {tc('actions.cancel')}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function LocalSignalsPage() {
  const { t } = useTranslation('worker')
  const { t: tc } = useTranslation('common')
  const { user } = useAuth()
  const { data, loading, error, reload } = useAsync<LocalSignals>(() =>
    api.get('/local-signals/'),
  )
  const [openCategory, setOpenCategory] = useState<string | null>(null)
  const [reportTarget, setReportTarget] = useState<ReportTarget | null>(null)
  const [reportedIds, setReportedIds] = useState<Set<number>>(new Set())
  const [confirmation, setConfirmation] = useState<string | null>(null)

  if (loading) return <Loading label={tc('states.loading')} />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const groups = data.grouped ?? []

  function handleSent() {
    if (!reportTarget) return
    setReportedIds((prev) => new Set(prev).add(reportTarget.signal.id))
    setReportTarget(null)
    setConfirmation(t('localSignals.reportSuccess'))
    window.setTimeout(() => setConfirmation(null), 4000)
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{tc('nav.localSignals')}</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {data.village
            ? `${data.village.name} · ${data.village.cluster}`
            : t('shared.noVillageAssigned')}
        </p>
      </div>

      {confirmation && (
        <div className="rounded-lg border border-care-200 bg-care-50 px-4 py-3 text-sm text-care-700">
          {confirmation}
        </div>
      )}

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

      <Card title={t('localSignals.categoryCardTitle', { count: groups.length })}>
        {groups.length === 0 ? (
          <Empty>{t('localSignals.noSignalsRecorded')}</Empty>
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
                        {t('localSignals.aboveBaseline')}
                      </span>
                    )}
                    <span className="text-xs text-ink-400">
                      {t('localSignals.recordCount', { count: group.signals.length })}
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
                            <th className="table-head">{t('localSignals.source')}</th>
                            <th className="table-head">{t('localSignals.week')}</th>
                            <th className="table-head">{t('localSignals.baseline')}</th>
                            <th className="table-head">{t('localSignals.reported')}</th>
                            <th className="table-head">{t('localSignals.change')}</th>
                            <th className="table-head" />
                          </tr>
                        </thead>
                        <tbody>
                          {group.signals.map((signal) => {
                            const rising = isAboveBaseline(signal)
                            const reported = reportedIds.has(signal.id)
                            return (
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
                                      {t('localSignals.notSubmitted')}
                                    </span>
                                  )}
                                </td>
                                <td className="table-cell">
                                  <Delta value={signal.change_pct} />
                                </td>
                                <td className="table-cell text-right">
                                  {rising &&
                                    (reported ? (
                                      <span className="text-xs text-care-700">
                                        {t('localSignals.reportedConfirmation')}
                                      </span>
                                    ) : (
                                      <button
                                        className="btn-ghost py-1 px-2 text-xs whitespace-nowrap"
                                        onClick={() =>
                                          setReportTarget({
                                            signal,
                                            categoryLabel: group.label,
                                          })
                                        }
                                      >
                                        {t('localSignals.reportToOfficer')}
                                      </button>
                                    ))}
                                </td>
                              </tr>
                            )
                          })}
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
            {data.scope_note}{' '}
            {t('localSignals.notSubmittedExplanation', {
              notSubmittedLabel: t('localSignals.notSubmitted'),
            })}
          </p>
        </div>
      </Card>

      {reportTarget && data.village && (
        <ReportToOfficerDialog
          target={reportTarget}
          villageName={data.village.name}
          workerName={user?.display_name ?? t('workCommunication.messages.you')}
          onCancel={() => setReportTarget(null)}
          onSent={handleSent}
        />
      )}
    </div>
  )
}
