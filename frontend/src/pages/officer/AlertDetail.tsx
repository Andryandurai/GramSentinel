import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import {
  Card,
  ErrorNote,
  Loading,
  SafetyPill,
  SeverityPill,
} from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { AlertEvidenceResponse, Outcome } from '@/types'

const OUTCOME_VALUES: Outcome[] = ['VALID_SIGNAL', 'FALSE_ALERT', 'RESOLVED']

export default function AlertDetail() {
  const { t } = useTranslation('officer')
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<AlertEvidenceResponse>(
    () => api.get(`/alerts/${id}/evidence/`),
    [id],
  )
  const OUTCOMES: Array<{ value: Outcome; label: string; help: string }> = OUTCOME_VALUES.map(
    (value) => ({
      value,
      label: t(`outcome.${value}.label`),
      help: t(`outcome.${value}.help`),
    }),
  )

  const [busy, setBusy] = useState(false)
  const [notes, setNotes] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState<string | null>(null)

  async function markInvestigating() {
    setBusy(true)
    setActionError(null)
    try {
      await api.patch(`/alerts/${id}/status/`, {
        status: 'UNDER_INVESTIGATION',
        notes,
      })
      reload()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t('alertDetail.humanDecision.updateError'))
    } finally {
      setBusy(false)
    }
  }

  async function recordOutcome(outcome: Outcome) {
    setBusy(true)
    setActionError(null)
    try {
      const response = await api.post<{ meaning: string }>(
        `/alerts/${id}/feedback/`,
        { outcome, notes },
      )
      setConfirmed(response.meaning)
      reload()
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t('alertDetail.humanDecision.recordError'))
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading label={t('alertDetail.loading')} />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const { alert, why_this_alert: why, cross_level: cross, relationships } = data
  const closed = alert.status === 'CLOSED'

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/officer/dashboard"
          className="text-xs text-ink-400 hover:text-ink-600"
        >
          {t('alertDetail.backToDashboard')}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{alert.title}</h1>
          <SeverityPill severity={alert.severity} />
          {data.safety_check && (
            <SafetyPill verdict={data.safety_check.verdict} />
          )}
        </div>
        <p className="text-sm text-ink-600 mt-1">
          {t('alertDetail.subtitle', {
            village: alert.village,
            cluster: alert.cluster,
            week: alert.week_label,
            start: alert.period_start,
            end: alert.period_end,
            confidence: alert.confidence.toFixed(2),
          })}
        </p>
      </div>

      <Card title={t('alertDetail.whyCard.title')}>
        <p className="text-sm text-ink-800">{why.explanation}</p>
        <p className="text-sm text-ink-600 mt-3">{alert.summary}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              {t('alertDetail.whyCard.corroborating', { count: why.corroborating_count })}
            </div>
            <p className="text-sm mt-1">
              {why.corroborating_sources.join(', ') || '—'}
            </p>
          </div>
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              {t('alertDetail.whyCard.supportingContext')}
            </div>
            <p className="text-sm mt-1">
              {why.context_sources.join(', ') || '—'}
            </p>
            <p className="text-xs text-ink-400 mt-1">
              {t('alertDetail.whyCard.notCounted')}
            </p>
          </div>
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              {t('alertDetail.whyCard.notReported')}
            </div>
            <p className="text-sm mt-1">
              {why.not_reported_sources.join(', ') || '—'}
            </p>
            <p className="text-xs text-ink-400 mt-1">
              {t('alertDetail.whyCard.recordedAsMissing')}
            </p>
          </div>
        </div>

        <div className="mt-4 rounded-md border border-violet-200 bg-violet-50 p-3">
          <div className="text-xs font-semibold text-violet-800">
            {t('alertDetail.crossLevel.title', { verdict: cross.verdict.toLowerCase() })}
          </div>
          <p className="text-sm text-violet-900 mt-1">{cross.statement}</p>
        </div>

        {relationships.anchor && (
          <div
            className={`mt-4 rounded-md border p-3 ${
              relationships.summary.has_disagreement
                ? 'border-amber-300 bg-amber-50'
                : 'border-care-200 bg-care-50'
            }`}
          >
            <div
              className={`text-xs font-semibold ${
                relationships.summary.has_disagreement
                  ? 'text-amber-900'
                  : 'text-care-700'
              }`}
            >
              {t('alertDetail.relationships.summary', {
                agree: relationships.summary.agree_count,
                disagree: relationships.summary.disagree_count,
              })}
            </div>
            <p
              className={`text-sm mt-1 ${
                relationships.summary.has_disagreement
                  ? 'text-amber-900'
                  : 'text-care-900'
              }`}
            >
              {relationships.summary.has_disagreement
                ? t('alertDetail.relationships.disagreeMessage')
                : t('alertDetail.relationships.agreeMessage')}
            </p>
          </div>
        )}

        <Link
          to={`/officer/alerts/${id}/evidence`}
          className="btn-sentinel mt-5"
        >
          {t('alertDetail.openEvidenceView')}
        </Link>
      </Card>

      <Card title={t('alertDetail.humanDecision.title')}>
        {confirmed ? (
          <div className="rounded-md border border-care-200 bg-care-50 px-4 py-3">
            <div className="text-sm font-medium text-care-700">
              {t('alertDetail.humanDecision.recorded')}
            </div>
            <p className="text-sm text-care-700 mt-1">{confirmed}</p>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm text-ink-600">
              {data.human_review.note}
            </p>

            <div>
              <label className="label" htmlFor="notes">
                {t('alertDetail.humanDecision.notesLabel')}
              </label>
              <textarea
                id="notes"
                rows={2}
                className="input"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder={t('alertDetail.humanDecision.notesPlaceholder')}
              />
            </div>

            {actionError && <ErrorNote message={actionError} />}

            {alert.status === 'DETECTED' && (
              <button
                className="btn-sentinel"
                onClick={markInvestigating}
                disabled={busy}
              >
                {busy ? t('alertDetail.humanDecision.updating') : t('alertDetail.humanDecision.markInvestigating')}
              </button>
            )}

            {!closed && (
              <div className="border-t border-ink-200 pt-4">
                <div className="label">
                  {t('alertDetail.humanDecision.recordOutcomeLabel')}
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  {OUTCOMES.map((outcome) => (
                    <button
                      key={outcome.value}
                      className="btn-ghost text-left flex-col items-start h-full"
                      onClick={() => recordOutcome(outcome.value)}
                      disabled={busy}
                    >
                      <span className="font-semibold">{outcome.label}</span>
                      <span className="text-xs text-ink-400 font-normal mt-1">
                        {outcome.help}
                      </span>
                    </button>
                  ))}
                </div>
                <p className="text-xs text-ink-400 mt-3">
                  {t('alertDetail.humanDecision.investigationNote')}
                </p>
              </div>
            )}

            {closed && (
              <p className="text-sm text-ink-600">
                {t('alertDetail.humanDecision.closedNote')}
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
