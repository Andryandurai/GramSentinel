import { type FormEvent, useEffect, useState } from 'react'
import { useLocation } from 'react-router-dom'

import { Card, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { ApiError, api } from '@/services/api'
import { useAuth } from '@/store/auth'
import { useOfflineSync } from '@/store/offlineSync'
import type { SymptomSummary } from '@/types'

interface CategoryOption {
  value: string
  label: string
  description_required: boolean
}

interface PipelineOutcome {
  category: string
  label: string
  reported_cases: number
  alert_raised: boolean
  reason: string
  safety_verdict: string
  corroborating_source_count: number
}

interface ReportResponse {
  ingestion: {
    channel: string
    records_received: number
    records_accepted: number
    records_rejected: number
    result: string
  }
  pipeline: PipelineOutcome[]
  described_observations: number
  officer_note: string
}

interface EntryRow {
  key: string
  category: string
  case_count: string
  description: string
}

let rowSeq = 0
const newRow = (category = ''): EntryRow => ({
  key: `row-${rowSeq++}`,
  category,
  case_count: '',
  description: '',
})

function currentWeek() {
  const now = new Date()
  const day = (now.getDay() + 6) % 7
  const monday = new Date(now)
  monday.setDate(now.getDate() - day)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)

  const thursday = new Date(monday)
  thursday.setDate(monday.getDate() + 3)
  const yearStart = new Date(thursday.getFullYear(), 0, 1)
  const week = Math.ceil(
    ((thursday.getTime() - yearStart.getTime()) / 86400000 + 1) / 7,
  )
  const iso = (d: Date) => d.toISOString().slice(0, 10)

  return {
    label: `${thursday.getFullYear()}-W${String(week).padStart(2, '0')}`,
    start: iso(monday),
    end: iso(sunday),
  }
}

export default function CommunityReportPage() {
  const { user } = useAuth()
  const location = useLocation()
  const week = currentWeek()
  const categories = useAsync<{ categories: CategoryOption[]; note: string }>(
    () => api.get('/report-categories/'),
  )

  // Arriving from the dashboard's Community Symptom Summary. The counts are
  // filled in for review — nothing is submitted until the worker submits it.
  const handoff = (location.state ?? null) as {
    prefill?: Array<{ category: string; case_count: number; label: string }>
    summary?: SymptomSummary
  } | null
  const prefill = handoff?.prefill?.filter((row) => row.category) ?? []

  const [meta, setMeta] = useState({
    week_label: week.label,
    period_start: week.start,
    period_end: week.end,
    unusual_observation: false,
    notes: '',
  })
  const [rows, setRows] = useState<EntryRow[]>(() =>
    prefill.length
      ? prefill.map((entry) => ({
          ...newRow(entry.category),
          case_count: String(entry.case_count),
        }))
      : [newRow('FEVER'), newRow('RESPIRATORY'), newRow('DIARRHOEAL')],
  )
  const [result, setResult] = useState<ReportResponse | null>(null)
  const [savedOffline, setSavedOffline] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const { status: connectivity, reports: queuedReports, init, retry } = useOfflineSync()
  useEffect(() => {
    init()
  }, [init])
  // This device's own queue, not filtered by village — a CHW's phone only
  // ever queues their own submissions, so there is nothing to scope here.
  const myPending = queuedReports.filter((r) => r.status !== 'synced')

  const options = categories.data?.categories ?? []
  const optionFor = (value: string) => options.find((o) => o.value === value)

  const updateRow = (key: string, patch: Partial<EntryRow>) =>
    setRows((prev) =>
      prev.map((row) => (row.key === key ? { ...row, ...patch } : row)),
    )

  const removeRow = (key: string) =>
    setRows((prev) => prev.filter((row) => row.key !== key))

  function validate(): string | null {
    const filled = rows.filter(
      (r) => r.category && (r.case_count.trim() !== '' || r.description.trim()),
    )
    if (filled.length === 0) {
      return 'Add at least one category with a number of reported cases, or describe what was observed.'
    }
    for (const row of filled) {
      const option = optionFor(row.category)
      if (option?.description_required && !row.description.trim()) {
        return `Describe what was observed for "${option.label}".`
      }
      if (row.case_count.trim() === '' && !row.description.trim()) {
        return `Enter a case count or a description for "${option?.label ?? row.category}".`
      }
    }
    return null
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!user?.village) {
      setError('No village is assigned to your account.')
      return
    }
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }

    setBusy(true)
    setError(null)
    setSavedOffline(false)

    const entries = rows
      .filter(
        (r) => r.category && (r.case_count.trim() !== '' || r.description.trim()),
      )
      .map((r) => ({
        category: r.category,
        case_count: Number(r.case_count || 0),
        description: r.description.trim(),
      }))

    const payload = { village: user.village, ...meta, entries }

    // Offline first: don't even attempt the network call if the browser
    // already knows it has no connection — go straight to the queue.
    if (connectivity === 'offline') {
      await useOfflineSync
        .getState()
        .enqueue(payload, user.village_name ?? '')
      setSavedOffline(true)
      setBusy(false)
      return
    }

    try {
      const response = await api.post<ReportResponse>('/community-reports/', payload)
      setResult(response)
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        // Reachability failed even though the browser thought it was
        // online — the report is not lost, it goes to the same queue.
        await useOfflineSync
          .getState()
          .enqueue(payload, user.village_name ?? '')
        setSavedOffline(true)
      } else {
        setError(err instanceof Error ? err.message : 'Could not submit.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (categories.loading) return <Loading label="Loading categories…" />

  const usedCategories = new Set(
    rows.filter((r) => r.category !== 'OTHER').map((r) => r.category),
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Community report</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          Village-level observations for {user?.village_name ?? 'your area'}.
          Counts by category only — never household identities.
        </p>
      </div>

      {myPending.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold text-amber-800">
              Pending reports ({myPending.length})
            </div>
            {connectivity !== 'offline' && (
              <button
                type="button"
                className="btn-ghost text-xs"
                onClick={() => void useOfflineSync.getState().syncNow()}
              >
                Sync now
              </button>
            )}
          </div>
          <ul className="mt-2 space-y-2">
            {myPending.map((queued) => (
              <li
                key={queued.client_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-white px-3 py-2 text-xs"
              >
                <span className="text-ink-700">
                  Report created {new Date(queued.created_at).toLocaleString()}
                  {queued.status === 'failed' && (
                    <span className="ml-2 text-red-700">⚠ Sync failed</span>
                  )}
                  {queued.status === 'syncing' && (
                    <span className="ml-2 text-amber-700">Syncing…</span>
                  )}
                  {queued.status === 'pending' && (
                    <span className="ml-2 text-ink-500">Pending sync</span>
                  )}
                </span>
                {queued.status === 'failed' && (
                  <button
                    type="button"
                    className="btn-ghost px-2 py-1 text-xs"
                    onClick={() => void retry(queued.client_id)}
                  >
                    Retry
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {savedOffline && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3">
          <div className="text-sm font-semibold text-amber-800">
            Saved on this device — waiting to sync
          </div>
          <p className="mt-1 text-xs text-amber-800">
            Could not reach the server, so nothing was lost — this report will
            send automatically once your connection returns.
          </p>
        </div>
      )}

      {handoff?.summary && !handoff.summary.is_empty && (
        <div className="rounded-lg border border-care-200 bg-care-50 px-4 py-3">
          <div className="text-sm font-semibold text-care-800">
            Prefilled from your community symptom summary
          </div>
          <p className="mt-1 text-sm text-care-900">
            {handoff.summary.total_people_assessed} people assessed
            {handoff.summary.is_all_weeks
              ? ' across all weeks'
              : ` · ${handoff.summary.period_label}`}
            {' — '}
            {handoff.summary.rows
              .map((row) => `${row.label} ${row.count}`)
              .join(' · ')}
            .
          </p>
          <p className="mt-1 text-xs text-care-800">
            Review and adjust every count before submitting. Nothing is sent to
            your health officer until you submit this report. Symptom rows with
            no matching community category — and anything else you observed —
            need to be added here yourself.
          </p>
        </div>
      )}

      <div className={`grid gap-6 ${result ? 'lg:grid-cols-2' : ''}`}>
        <Card title="Reported health signals this week">
          <form onSubmit={submit} className="space-y-5">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="label" htmlFor="week">
                  Week
                </label>
                <input
                  id="week"
                  className="input"
                  value={meta.week_label}
                  onChange={(e) =>
                    setMeta((m) => ({ ...m, week_label: e.target.value }))
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="start">
                  From
                </label>
                <input
                  id="start"
                  type="date"
                  className="input"
                  value={meta.period_start}
                  onChange={(e) =>
                    setMeta((m) => ({ ...m, period_start: e.target.value }))
                  }
                />
              </div>
              <div>
                <label className="label" htmlFor="end">
                  To
                </label>
                <input
                  id="end"
                  type="date"
                  className="input"
                  value={meta.period_end}
                  onChange={(e) =>
                    setMeta((m) => ({ ...m, period_end: e.target.value }))
                  }
                />
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-baseline justify-between">
                <span className="label mb-0">Observed health concerns</span>
                <span className="text-xs text-ink-400">
                  Reported cases, not confirmed diagnoses
                </span>
              </div>

              {rows.map((row) => {
                const option = optionFor(row.category)
                const needsDescription = option?.description_required ?? false
                return (
                  <div
                    key={row.key}
                    className="rounded-md border border-ink-200 p-3 space-y-2"
                  >
                    <div className="flex gap-2">
                      <select
                        className="input flex-1"
                        value={row.category}
                        onChange={(e) =>
                          updateRow(row.key, { category: e.target.value })
                        }
                        aria-label="Category"
                      >
                        <option value="">Select a category…</option>
                        {options.map((option2) => (
                          <option
                            key={option2.value}
                            value={option2.value}
                            disabled={
                              option2.value !== 'OTHER' &&
                              option2.value !== row.category &&
                              usedCategories.has(option2.value)
                            }
                          >
                            {option2.label}
                            {option2.description_required
                              ? ' — description required'
                              : ''}
                          </option>
                        ))}
                      </select>
                      <input
                        type="number"
                        min={0}
                        className="input w-24"
                        placeholder="Cases"
                        value={row.case_count}
                        onChange={(e) =>
                          updateRow(row.key, { case_count: e.target.value })
                        }
                        aria-label="Reported cases"
                      />
                      {rows.length > 1 && (
                        <button
                          type="button"
                          className="btn-ghost px-3"
                          onClick={() => removeRow(row.key)}
                          aria-label="Remove"
                        >
                          ×
                        </button>
                      )}
                    </div>

                    {row.category && (
                      <textarea
                        rows={needsDescription ? 3 : 2}
                        className="input text-sm"
                        placeholder={
                          needsDescription
                            ? 'Required — describe what was observed, and any relevant context.'
                            : 'Optional notes about what was observed.'
                        }
                        value={row.description}
                        onChange={(e) =>
                          updateRow(row.key, { description: e.target.value })
                        }
                      />
                    )}
                  </div>
                )
              })}

              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-ghost text-sm"
                  onClick={() => setRows((prev) => [...prev, newRow()])}
                >
                  + Add category
                </button>
                <button
                  type="button"
                  className="btn-ghost text-sm"
                  onClick={() => setRows((prev) => [...prev, newRow('OTHER')])}
                >
                  + Other health concern
                </button>
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="rounded border-ink-200"
                checked={meta.unusual_observation}
                onChange={(e) =>
                  setMeta((m) => ({
                    ...m,
                    unusual_observation: e.target.checked,
                  }))
                }
              />
              Flag as unusual for this village
            </label>

            <div>
              <label className="label" htmlFor="notes">
                General notes
              </label>
              <textarea
                id="notes"
                rows={2}
                className="input"
                value={meta.notes}
                onChange={(e) =>
                  setMeta((m) => ({ ...m, notes: e.target.value }))
                }
              />
            </div>

            {error && <ErrorNote message={error} />}

            <button type="submit" className="btn-care w-full" disabled={busy}>
              {busy ? 'Submitting…' : 'Submit report'}
            </button>
          </form>
        </Card>

        {result && (
          <Card title="Report submitted">
            <div className="space-y-4">
              <div className="rounded-md border border-care-200 bg-care-50 px-3 py-2">
                <div className="text-sm font-medium text-care-700">
                  Report submitted
                </div>
                <p className="text-xs text-care-700 mt-1">
                  {result.officer_note}
                  {result.described_observations > 0 &&
                    ` ${result.described_observations} described observation(s) included.`}
                </p>
              </div>

              {result.pipeline.length > 0 && (
                <div>
                  <div className="label">Result by category</div>
                  <ul className="space-y-2">
                    {result.pipeline.map((outcome) => (
                      <li
                        key={outcome.category}
                        className="rounded-md border border-ink-200 px-3 py-2"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium">
                            {outcome.label}
                          </span>
                          <span className="text-xs text-ink-400">
                            {outcome.reported_cases} reported
                          </span>
                          <span
                            className={`pill ml-auto ${
                              outcome.safety_verdict === 'PASS'
                                ? 'bg-care-100 text-care-700'
                                : 'bg-ink-100 text-ink-600'
                            }`}
                          >
                            {outcome.corroborating_source_count} source(s)
                          </span>
                        </div>
                        <p className="text-xs text-ink-600 mt-1">
                          {outcome.alert_raised
                            ? 'Raised for health-officer review.'
                            : outcome.reason ||
                              'Recorded. Not escalated — no other source corroborates it yet.'}
                        </p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <button
                className="btn-ghost w-full"
                onClick={() => setResult(null)}
              >
                Submit another report
              </button>
            </div>
          </Card>
        )}
      </div>
    </div>
  )
}
