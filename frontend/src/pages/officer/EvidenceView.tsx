import { Link, useParams } from 'react-router-dom'

import { AgentTrace } from '@/components/AgentTrace'
import { SafetyPanel } from '@/components/SafetyPanel'
import { Card, Delta, ErrorNote, Loading, SeverityPill } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type { AlertEvidenceResponse, EvidenceCard } from '@/types'

const STATUS_STYLES: Record<string, string> = {
  ANOMALY_DETECTED: 'border-red-300 bg-red-50',
  CORROBORATING: 'border-orange-300 bg-orange-50',
  SUPPORTING_CONTEXT: 'border-ink-200 bg-ink-50',
  NORMAL: 'border-ink-200 bg-white',
  NOT_REPORTED: 'border-dashed border-ink-300 bg-white',
  INSUFFICIENT_DATA: 'border-dashed border-amber-300 bg-amber-50/40',
}

/** One agent's structured finding, rendered the way it was produced. */
function EvidenceCardView({ card }: { card: EvidenceCard }) {
  return (
    <article
      className={`rounded-lg border p-4 ${
        STATUS_STYLES[card.status] ?? 'border-ink-200 bg-white'
      }`}
    >
      <header className="flex items-center gap-2">
        <span className="font-semibold text-sm">{card.source_kind}</span>
        {card.is_corroborating && (
          <span className="pill bg-sentinel-100 text-sentinel-700">
            corroborating
          </span>
        )}
        <span className="ml-auto text-xs font-mono text-ink-400">
          {card.week_label}
        </span>
      </header>

      <p className="text-xs text-ink-400 mt-0.5">{card.source_name}</p>

      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-ink-400">Baseline</dt>
          <dd className="font-mono">{card.baseline ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">Current</dt>
          <dd className="font-mono">
            {card.current_value === null ? (
              <span className="italic text-ink-400">not submitted</span>
            ) : (
              `${card.current_value}${card.unit ? ` ${card.unit}` : ''}`
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">Change</dt>
          <dd>
            <Delta value={card.change_pct} />
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex items-center gap-2 text-xs">
        <span className="font-semibold">{card.status.replace(/_/g, ' ')}</span>
        <span className="text-ink-400">·</span>
        <span className="text-ink-600">data quality {card.data_quality}</span>
      </div>

      <p className="mt-2 text-xs text-ink-600 leading-relaxed">
        {card.explanation}
      </p>

      <p className="mt-2 text-xs text-ink-400 font-mono">
        produced by {card.produced_by_agent}
      </p>
    </article>
  )
}

export default function EvidenceView() {
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<AlertEvidenceResponse>(
    () => api.get(`/alerts/${id}/evidence/`),
    [id],
  )

  if (loading) return <Loading label="Loading evidence…" />
  if (error) return <ErrorNote message={error} onRetry={reload} />
  if (!data) return null

  const { alert, why_this_alert: why, safety_check: safety } = data

  return (
    <div className="space-y-6">
      <div>
        <Link
          to={`/officer/alerts/${id}`}
          className="text-xs text-ink-400 hover:text-ink-600"
        >
          ← Alert
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">
            Evidence view
          </h1>
          <SeverityPill severity={alert.severity} />
        </div>
        <p className="text-sm text-ink-600 mt-1">
          {alert.title} · {alert.cluster} · {alert.week_label}
        </p>
      </div>

      <Card title={`Source-by-source evidence (${data.evidence.length} sources)`}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.evidence.map((card) => (
            <EvidenceCardView key={card.id} card={card} />
          ))}
        </div>
        <p className="text-xs text-ink-400 mt-4">
          {why.corroborating_count} independent source(s) count toward
          corroboration. Weather is context only. Sources that did not submit
          are shown as missing rather than zero.
        </p>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Cross-Level Intelligence">
          <div className="rounded-md border border-violet-200 bg-violet-50 p-3">
            <div className="text-xs font-semibold text-violet-800">
              Verdict — {data.cross_level.verdict.toLowerCase()}
            </div>
            <p className="text-sm text-violet-900 mt-1 leading-relaxed">
              {data.cross_level.statement}
            </p>
          </div>
          <p className="text-xs text-ink-400 mt-3 leading-relaxed">
            This comparison is performed on aggregated counts only. No patient
            record crosses from RuralCare into community analysis, so the
            linkage happens without centralising identifiable data.
          </p>
        </Card>

        <Card title="Deterministic Safety Engine">
          {safety ? (
            <SafetyPanel
              verdict={safety.verdict}
              status={safety.status}
              rules={safety.rules}
              reasons={safety.reasons}
              engineVersion={safety.engine_version}
            />
          ) : (
            <p className="text-sm text-ink-400">No safety check recorded.</p>
          )}
        </Card>
      </div>

      <Card
        title={`Agent handoffs (${data.agent_trace.length} invocations)`}
        action={
          <span className="text-xs text-ink-400">
            {alert.narrative_used_llm
              ? 'LLM used for narrative wording only'
              : 'Fully deterministic run — no LLM used'}
          </span>
        }
      >
        <AgentTrace trace={data.agent_trace} />
      </Card>

      <div className="rounded-lg border border-sentinel-200 bg-sentinel-50 px-4 py-3">
        <div className="text-sm font-semibold text-sentinel-700">
          Human review required
        </div>
        <p className="text-sm text-sentinel-900 mt-1">
          {data.human_review.note}
        </p>
      </div>
    </div>
  )
}
