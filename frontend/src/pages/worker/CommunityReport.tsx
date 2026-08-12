import { type FormEvent, useState } from 'react'

import { Card, Disclaimer, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'

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
  const week = currentWeek()
  const categories = useAsync<{ categories: CategoryOption[]; note: string }>(
    () => api.get('/report-categories/'),
  )

  const [meta, setMeta] = useState({
    week_label: week.label,
    period_start: week.start,
    period_end: week.end,
    unusual_observation: false,
    notes: '',
  })
  const [rows, setRows] = useState<EntryRow[]>([
    newRow('FEVER'),
    newRow('RESPIRATORY'),
    newRow('DIARRHOEAL'),
  ])
  const [result, setResult] = useState<ReportResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    try {
      const entries = rows
        .filter(
          (r) =>
            r.category && (r.case_count.trim() !== '' || r.description.trim()),
        )
        .map((r) => ({
          category: r.category,
          case_count: Number(r.case_count || 0),
          description: r.description.trim(),
        }))

      const response = await api.post<ReportResponse>('/community-reports/', {
        village: user.village,
        ...meta,
        entries,
      })
      setResult(response)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not submit.')
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

      <div className="grid gap-6 lg:grid-cols-2">
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
            <Disclaimer />
          </form>
        </Card>

        <div className="space-y-6">
          <Card title="What happens after you submit">
            {!result ? (
              <ol className="space-y-3 text-sm text-ink-600">
                {[
                  'Your report is validated and normalised.',
                  'Each community source is compared against its own baseline.',
                  'Signals that move together are assembled into a candidate pattern.',
                  'Anonymised patient activity is checked against it.',
                  'Deterministic safety rules pass, downgrade or block the result.',
                  'The health officer for your village reviews what survives.',
                ].map((line, index) => (
                  <li key={line} className="flex gap-3">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink-100 text-xs font-semibold text-ink-600">
                      {index + 1}
                    </span>
                    {line}
                  </li>
                ))}
              </ol>
            ) : (
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
            )}
          </Card>

          <Card title="About these categories">
            <p className="text-sm text-ink-600">
              {categories.data?.note}
            </p>
            <p className="mt-2 text-xs text-ink-400">
              If something does not fit a listed category, use{' '}
              <span className="font-medium">Other health concern</span> and
              describe it in your own words. The health officer for your village
              sees your description exactly as you wrote it.
            </p>
          </Card>
        </div>
      </div>
    </div>
  )
}
