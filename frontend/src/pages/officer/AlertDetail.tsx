import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

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

const OUTCOMES: Array<{ value: Outcome; label: string; help: string }> = [
  {
    value: 'VALID_SIGNAL',
    label: 'Valid signal',
    help: 'The alert was justified and the investigation was warranted. This is not confirmation of any disease or outbreak.',
  },
  {
    value: 'FALSE_ALERT',
    label: 'False alert',
    help: 'Investigation found no meaningful underlying pattern. Reviewed for threshold or data-quality adjustment.',
  },
  {
    value: 'RESOLVED',
    label: 'Resolved',
    help: 'The situation was addressed or explained and needs no further action.',
  },
]

export default function AlertDetail() {
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<AlertEvidenceResponse>(
    () => api.get(`/alerts/${id}/evidence/`),
    [id],
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
      setActionError(err instanceof Error ? err.message : 'Could not update.')
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
      setActionError(err instanceof Error ? err.message : 'Could not record.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Loading label="Loading alert…" />
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
          ← Dashboard
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">{alert.title}</h1>
          <SeverityPill severity={alert.severity} />
          {data.safety_check && (
            <SafetyPill verdict={data.safety_check.verdict} />
          )}
        </div>
        <p className="text-sm text-ink-600 mt-1">
          {alert.village} · {alert.cluster} · {alert.week_label} (
          {alert.period_start} to {alert.period_end}) · confidence{' '}
          <span className="font-mono">{alert.confidence.toFixed(2)}</span>
        </p>
      </div>

      <Card title="Why was this alert generated?">
        <p className="text-sm text-ink-800">{why.explanation}</p>
        <p className="text-sm text-ink-600 mt-3">{alert.summary}</p>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              Corroborating ({why.corroborating_count})
            </div>
            <p className="text-sm mt-1">
              {why.corroborating_sources.join(', ') || '—'}
            </p>
          </div>
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              Supporting context
            </div>
            <p className="text-sm mt-1">
              {why.context_sources.join(', ') || '—'}
            </p>
            <p className="text-xs text-ink-400 mt-1">
              Does not count toward corroboration.
            </p>
          </div>
          <div className="rounded-md border border-ink-200 p-3">
            <div className="text-xs font-semibold text-ink-600">
              Not reported
            </div>
            <p className="text-sm mt-1">
              {why.not_reported_sources.join(', ') || '—'}
            </p>
            <p className="text-xs text-ink-400 mt-1">
              Recorded as missing, never as zero.
            </p>
          </div>
        </div>

        <div className="mt-4 rounded-md border border-violet-200 bg-violet-50 p-3">
          <div className="text-xs font-semibold text-violet-800">
            Cross-Level Intelligence — {cross.verdict.toLowerCase()}
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
              Evidence relationships — {relationships.summary.agree_count} agree
              · {relationships.summary.disagree_count} disagree
            </div>
            <p
              className={`text-sm mt-1 ${
                relationships.summary.has_disagreement
                  ? 'text-amber-900'
                  : 'text-care-900'
              }`}
            >
              {relationships.summary.has_disagreement
                ? 'At least one source disagrees with the rest — see the evidence view for why.'
                : 'The comparable sources for this alert agree with each other.'}
            </p>
          </div>
        )}

        <Link
          to={`/officer/alerts/${id}/evidence`}
          className="btn-sentinel mt-5"
        >
          Open full evidence view
        </Link>
      </Card>

      <Card title="Human decision">
        {confirmed ? (
          <div className="rounded-md border border-care-200 bg-care-50 px-4 py-3">
            <div className="text-sm font-medium text-care-700">
              Outcome recorded — feedback stored
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
                Investigation notes
              </label>
              <textarea
                id="notes"
                rows={2}
                className="input"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="What did you or the field team find?"
              />
            </div>

            {actionError && <ErrorNote message={actionError} />}

            {alert.status === 'DETECTED' && (
              <button
                className="btn-sentinel"
                onClick={markInvestigating}
                disabled={busy}
              >
                {busy ? 'Updating…' : 'Mark under investigation'}
              </button>
            )}

            {!closed && (
              <div className="border-t border-ink-200 pt-4">
                <div className="label">
                  Record the outcome after real-world investigation
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
                  Real-world investigation happens outside this platform, by
                  people rather than software.
                </p>
              </div>
            )}

            {closed && (
              <p className="text-sm text-ink-600">
                This alert is closed and its outcome has been recorded.
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
