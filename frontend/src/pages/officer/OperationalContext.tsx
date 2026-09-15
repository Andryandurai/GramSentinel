import { type FormEvent, useState } from 'react'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type {
  DataSourceRow,
  OperationalContextMode,
  SourceOperationalContext,
} from '@/types'

const MODE_LABELS: Record<OperationalContextMode, string> = {
  TEMPORARILY_UNAVAILABLE: 'Temporarily unavailable',
  EXPECTED_VARIATION: 'Expected unusual activity',
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

interface ConfigureDialogProps {
  source: DataSourceRow
  existing: SourceOperationalContext | null
  onClose: () => void
  onSaved: () => void
}

function ConfigureDialog({ source, existing, onClose, onSaved }: ConfigureDialogProps) {
  const [mode, setMode] = useState<OperationalContextMode>(existing?.mode ?? 'TEMPORARILY_UNAVAILABLE')
  const [reason, setReason] = useState(existing?.reason ?? '')
  const [notes, setNotes] = useState(existing?.notes ?? '')
  const [startsOn, setStartsOn] = useState(existing?.starts_on ?? today())
  const [endsOn, setEndsOn] = useState(existing?.ends_on ?? today())
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!reason.trim()) {
      setError('A reason is required — e.g. "School holiday".')
      return
    }
    if (startsOn > endsOn) {
      setError('The period cannot end before it starts.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const payload = {
        source: source.id,
        mode,
        reason: reason.trim(),
        notes: notes.trim(),
        starts_on: startsOn,
        ends_on: endsOn,
      }
      if (existing) {
        await api.patch(`/source-contexts/${existing.id}/`, payload)
      } else {
        await api.post('/source-contexts/', payload)
      }
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 px-4"
      onClick={onClose}
    >
      <form
        onSubmit={save}
        className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl space-y-4"
        onClick={(event) => event.stopPropagation()}
      >
        <div>
          <h2 className="text-base font-semibold text-ink-900">{source.name}</h2>
          <p className="text-xs text-ink-500">Configure operational context</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={mode === 'TEMPORARILY_UNAVAILABLE'}
              onChange={() => setMode('TEMPORARILY_UNAVAILABLE')}
            />
            Temporarily unavailable
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={mode === 'EXPECTED_VARIATION'}
              onChange={() => setMode('EXPECTED_VARIATION')}
            />
            Expected unusual activity
          </label>
        </div>

        <div>
          <label className="label" htmlFor="oc-reason">Reason</label>
          <input
            id="oc-reason"
            className="input"
            placeholder="e.g. School holiday"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="oc-start">From</label>
            <input
              id="oc-start"
              type="date"
              className="input"
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="oc-end">Until</label>
            <input
              id="oc-end"
              type="date"
              className="input"
              value={endsOn}
              onChange={(e) => setEndsOn(e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="label" htmlFor="oc-notes">Notes (optional)</label>
          <textarea
            id="oc-notes"
            rows={2}
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <p className="text-xs text-ink-500">
          The source remains visible and its reported values are preserved.
          This only changes how the reading is interpreted for the period
          above — it will not count toward independent corroboration.
        </p>

        {error && <ErrorNote message={error} />}

        <div className="flex gap-2">
          <button type="submit" className="btn-care flex-1" disabled={busy}>
            {busy ? 'Saving…' : 'Save context'}
          </button>
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </form>
    </div>
  )
}

function SourceRow({
  source,
  context,
  onChanged,
}: {
  source: DataSourceRow
  context: SourceOperationalContext | undefined
  onChanged: () => void
}) {
  const [showDialog, setShowDialog] = useState(false)
  const [busy, setBusy] = useState(false)

  const active = context && context.is_applicable_now && !context.is_cancelled

  async function restoreNow() {
    if (!context) return
    setBusy(true)
    try {
      await api.post(`/source-contexts/${context.id}/cancel/`)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-md border border-ink-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-sm">{source.name}</span>
        {active ? (
          <span className="pill bg-amber-100 text-amber-800">
            {MODE_LABELS[context.mode]}
          </span>
        ) : (
          <span className="pill bg-care-100 text-care-700">Active</span>
        )}
      </div>

      {active ? (
        <>
          <p className="mt-1.5 text-sm text-ink-700">{context.reason}</p>
          <p className="text-xs text-ink-500">
            {context.starts_on} → {context.ends_on} · Excluded from independent
            corroboration · Automatically resumes after {context.ends_on}
          </p>
          <div className="mt-2 flex gap-2">
            <button
              className="btn-ghost text-xs"
              onClick={() => setShowDialog(true)}
              disabled={busy}
            >
              Edit
            </button>
            <button className="btn-ghost text-xs" onClick={restoreNow} disabled={busy}>
              Restore now
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="mt-1 text-xs text-ink-500">Signals interpreted normally.</p>
          <button
            className="btn-ghost mt-2 text-xs"
            onClick={() => setShowDialog(true)}
          >
            Configure
          </button>
        </>
      )}

      {showDialog && (
        <ConfigureDialog
          source={source}
          existing={active ? context! : null}
          onClose={() => setShowDialog(false)}
          onSaved={() => {
            setShowDialog(false)
            onChanged()
          }}
        />
      )}
    </div>
  )
}

export default function OperationalContextPage() {
  const { user } = useAuth()
  const sources = useAsync<DataSourceRow[]>(
    () => api.get(user?.village_code ? `/data-sources/?village=${user.village_code}` : '/data-sources/'),
    [user?.village_code],
  )
  const contexts = useAsync<SourceOperationalContext[]>(() => api.get('/source-contexts/'))

  if (sources.loading || contexts.loading) return <Loading label="Loading operational context…" />
  if (sources.error) return <ErrorNote message={sources.error} onRetry={sources.reload} />
  if (contexts.error) return <ErrorNote message={contexts.error} onRetry={contexts.reload} />

  const rows = sources.data ?? []
  const byContext = new Map<number, SourceOperationalContext>()
  for (const context of contexts.data ?? []) {
    if (context.is_applicable_now && !context.is_cancelled) {
      byContext.set(context.source, context)
    }
  }

  function reloadAll() {
    sources.reload()
    contexts.reload()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Operational context</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {user?.village_name ?? 'Your area'} — record a known reason a source
          should not count toward independent corroboration for a specific
          period. Raw reported values are always preserved.
        </p>
      </div>

      <Card title="Data sources">
        {rows.length === 0 ? (
          <Empty>No data sources registered for this village.</Empty>
        ) : (
          <div className="space-y-3">
            {rows.map((source) => (
              <SourceRow
                key={source.id}
                source={source}
                context={byContext.get(source.id)}
                onChanged={reloadAll}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
