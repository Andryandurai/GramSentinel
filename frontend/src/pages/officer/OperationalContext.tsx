import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Card, Empty, ErrorNote, Loading } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useAuth } from '@/store/auth'
import type {
  DataSourceRow,
  OperationalContextMode,
  SourceOperationalContext,
} from '@/types'

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
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
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
      setError(t('operationalContext.dialog.reasonRequired'))
      return
    }
    if (startsOn > endsOn) {
      setError(t('operationalContext.dialog.invalidRange'))
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
      setError(err instanceof Error ? err.message : tc('validation.genericSaveError'))
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
          <p className="text-xs text-ink-500">{t('operationalContext.dialog.subtitle')}</p>
        </div>

        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={mode === 'TEMPORARILY_UNAVAILABLE'}
              onChange={() => setMode('TEMPORARILY_UNAVAILABLE')}
            />
            {t('operationalContext.mode.TEMPORARILY_UNAVAILABLE')}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={mode === 'EXPECTED_VARIATION'}
              onChange={() => setMode('EXPECTED_VARIATION')}
            />
            {t('operationalContext.mode.EXPECTED_VARIATION')}
          </label>
        </div>

        <div>
          <label className="label" htmlFor="oc-reason">{t('operationalContext.dialog.reasonLabel')}</label>
          <input
            id="oc-reason"
            className="input"
            placeholder={t('operationalContext.dialog.reasonPlaceholder')}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="oc-start">{t('operationalContext.dialog.fromLabel')}</label>
            <input
              id="oc-start"
              type="date"
              className="input"
              value={startsOn}
              onChange={(e) => setStartsOn(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="oc-end">{t('operationalContext.dialog.untilLabel')}</label>
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
          <label className="label" htmlFor="oc-notes">{t('operationalContext.dialog.notesLabel')}</label>
          <textarea
            id="oc-notes"
            rows={2}
            className="input"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </div>

        <p className="text-xs text-ink-500">
          {t('operationalContext.dialog.helper')}
        </p>

        {error && <ErrorNote message={error} />}

        <div className="flex gap-2">
          <button type="submit" className="btn-care flex-1" disabled={busy}>
            {busy ? tc('actions.saving') : t('operationalContext.dialog.saveButton')}
          </button>
          <button type="button" className="btn-ghost" onClick={onClose} disabled={busy}>
            {tc('actions.cancel')}
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
  const { t } = useTranslation('officer')
  const { t: tc } = useTranslation('common')
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
            {t(`operationalContext.mode.${context.mode}`)}
          </span>
        ) : (
          <span className="pill bg-care-100 text-care-700">{tc('status.ACTIVE')}</span>
        )}
      </div>

      {active ? (
        <>
          <p className="mt-1.5 text-sm text-ink-700">{context.reason}</p>
          <p className="text-xs text-ink-500">
            {context.starts_on} → {context.ends_on} · {t('shared.excludedFromCorroboration')} ·{' '}
            {t('operationalContext.row.autoResumes', { date: context.ends_on })}
          </p>
          <div className="mt-2 flex gap-2">
            <button
              className="btn-ghost text-xs"
              onClick={() => setShowDialog(true)}
              disabled={busy}
            >
              {tc('actions.edit')}
            </button>
            <button className="btn-ghost text-xs" onClick={restoreNow} disabled={busy}>
              {t('operationalContext.row.restoreNow')}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="mt-1 text-xs text-ink-500">{t('operationalContext.row.normalNote')}</p>
          <button
            className="btn-ghost mt-2 text-xs"
            onClick={() => setShowDialog(true)}
          >
            {t('operationalContext.row.configure')}
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
  const { t } = useTranslation('officer')
  const { user } = useAuth()
  const sources = useAsync<DataSourceRow[]>(
    () => api.get(user?.village_code ? `/data-sources/?village=${user.village_code}` : '/data-sources/'),
    [user?.village_code],
  )
  const contexts = useAsync<SourceOperationalContext[]>(() => api.get('/source-contexts/'))

  if (sources.loading || contexts.loading) return <Loading label={t('operationalContext.loading')} />
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
        <h1 className="text-xl font-semibold tracking-tight">{t('operationalContext.title')}</h1>
        <p className="text-sm text-ink-600 mt-0.5">
          {t('operationalContext.subtitle', {
            village: user?.village_name ?? t('shared.scopeYourArea'),
          })}
        </p>
      </div>

      <Card title={t('operationalContext.dataSourcesTitle')}>
        {rows.length === 0 ? (
          <Empty>{t('operationalContext.noSources')}</Empty>
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
