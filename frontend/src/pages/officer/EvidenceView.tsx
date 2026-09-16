import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { AgentTrace } from '@/components/AgentTrace'
import { RagGuidancePanel } from '@/components/RagGuidancePanel'
import { SafetyPanel } from '@/components/SafetyPanel'
import { Card, Delta, ErrorNote, FreshnessPill, Loading, SeverityPill } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import type {
  AlertEvidenceResponse,
  EvidenceCard,
  EvidenceRelationshipContext,
  EvidenceRelationshipEdge,
  EvidenceRelationships,
  RagResponse,
} from '@/types'

const STATUS_STYLES: Record<string, string> = {
  ANOMALY_DETECTED: 'border-red-300 bg-red-50',
  CORROBORATING: 'border-orange-300 bg-orange-50',
  SUPPORTING_CONTEXT: 'border-ink-200 bg-ink-50',
  NORMAL: 'border-ink-200 bg-white',
  NOT_REPORTED: 'border-dashed border-ink-300 bg-white',
  INSUFFICIENT_DATA: 'border-dashed border-amber-300 bg-amber-50/40',
  // Operational Context — a known, human-recorded operational condition,
  // deliberately styled distinctly from both "anomaly" (red) and "missing
  // data" (dashed) — this is neither a system failure nor unexplained.
  EXPECTED_UNAVAILABLE: 'border-sky-300 bg-sky-50',
  EXPECTED_VARIATION: 'border-sky-300 bg-sky-50',
}

/**
 * One source-pair relationship — a single row of the hub-and-spoke map, with
 * the full source-A / source-B / reason breakdown available on expand.
 * Agreement and disagreement are distinguished by both colour and an
 * explicit "Agrees" / "Disagrees" label, never colour alone.
 */
function RelationshipEdgeRow({ edge }: { edge: EvidenceRelationshipEdge }) {
  const { t } = useTranslation('officer')
  const [open, setOpen] = useState(false)
  const agree = edge.relationship === 'AGREE'

  return (
    <li
      className={`rounded-lg border ${agree ? 'border-care-200 bg-care-50/40' : 'border-amber-300 bg-amber-50/50'}`}
    >
      <button
        className="w-full flex flex-wrap items-center gap-2 px-3 py-2.5 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="text-sm font-medium">{edge.source_a}</span>
        <span
          className={`pill ${agree ? 'bg-care-100 text-care-700' : 'bg-amber-100 text-amber-800'}`}
        >
          {agree ? `✓ ${t('evidenceView.relationshipMap.agrees')}` : `⚠ ${t('evidenceView.relationshipMap.disagrees')}`}
        </span>
        <span className="text-sm font-medium">{edge.source_b}</span>
        <span className="ml-auto text-ink-400 text-xs">{open ? '▾' : '▸'}</span>
      </button>
      <p className="px-3 pb-2 -mt-1 text-xs text-ink-600">{edge.statement}</p>

      {open && (
        <div className="border-t border-ink-200 px-3 py-3 space-y-2 text-xs">
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="rounded-md border border-ink-200 bg-white p-2">
              <div className="font-semibold text-ink-700">{edge.source_a}</div>
              <p className="mt-1 text-ink-600">{edge.what_a_reported}</p>
            </div>
            <div className="rounded-md border border-ink-200 bg-white p-2">
              <div className="font-semibold text-ink-700">{edge.source_b}</div>
              <p className="mt-1 text-ink-600">{edge.what_b_reported}</p>
            </div>
          </div>
          <div>
            <span className="font-semibold text-ink-700">{t('evidenceView.relationshipMap.reasonLabel')} </span>
            <span className="text-ink-600">{edge.reason}</span>
          </div>
          {edge.investigate && (
            <p className="rounded-md border border-amber-300 bg-amber-50 px-2 py-1.5 text-amber-900">
              {edge.investigate}
            </p>
          )}
        </div>
      )}
    </li>
  )
}

function NotComparableRow({ item }: { item: EvidenceRelationshipContext }) {
  const { t } = useTranslation('officer')
  const [open, setOpen] = useState(false)
  return (
    <li className="rounded-lg border border-ink-200 bg-ink-50/60">
      <button
        className="w-full flex flex-wrap items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="text-sm font-medium">{item.source_name}</span>
        <span className="pill bg-ink-100 text-ink-500">{t('evidenceView.relationshipMap.notComparableLabel')}</span>
        <span className="ml-auto text-ink-400 text-xs">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <p className="px-3 pb-2 -mt-1 text-xs text-ink-600">{item.reason}</p>
      )}
    </li>
  )
}

/**
 * Evidence Relationship Map — states, for this one alert, which sources
 * agree, which disagree, and which cannot be directly compared, relative to
 * whichever source most likely drove the alert. Read-only decision support:
 * it never declares an outbreak, closes an alert, or overrides the safety
 * engine — it only makes explicit a relationship an officer could otherwise
 * only notice by reading every evidence card by eye.
 */
function EvidenceRelationshipMap({
  relationships,
}: {
  relationships: EvidenceRelationships
}) {
  const { t } = useTranslation('officer')
  const { anchor, edges, context, summary } = relationships

  if (!anchor) {
    return (
      <Card title={t('evidenceView.relationshipMap.title')}>
        <p className="text-sm text-ink-600">
          {t('evidenceView.relationshipMap.onlyOneSource')}
        </p>
      </Card>
    )
  }

  return (
    <Card
      title={t('evidenceView.relationshipMap.title')}
      action={
        <span className="text-xs text-ink-400">
          {t('evidenceView.relationshipMap.summary', {
            agree: summary.agree_count,
            disagree: summary.disagree_count,
            notComparable: summary.not_comparable_count,
          })}
        </span>
      }
    >
      <p className="text-sm text-ink-600">
        {t('evidenceView.relationshipMap.descriptionPrefix')}{' '}
        <span className="font-semibold">{anchor.source_kind_display}</span>
        {t('evidenceView.relationshipMap.descriptionSuffix')}
      </p>

      {summary.has_disagreement && (
        <p className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {t('evidenceView.relationshipMap.disagreementWarning')}
        </p>
      )}

      {edges.length > 0 && (
        <ul className="mt-4 space-y-2">
          {edges.map((edge) => (
            <RelationshipEdgeRow
              key={`${edge.source_a_kind}-${edge.source_b_kind}`}
              edge={edge}
            />
          ))}
        </ul>
      )}

      {context.length > 0 && (
        <>
          <div className="label mt-4">{t('evidenceView.relationshipMap.notComparableLabel')}</div>
          <ul className="mt-1 space-y-2">
            {context.map((item) => (
              <NotComparableRow key={item.source_kind} item={item} />
            ))}
          </ul>
        </>
      )}

      <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
        {t('evidenceView.relationshipMap.footer')}
      </p>
    </Card>
  )
}

/** One agent's structured finding, rendered the way it was produced. */
function EvidenceCardView({ card }: { card: EvidenceCard }) {
  const { t } = useTranslation('officer')
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
            {t('evidenceView.evidenceCard.corroborating')}
          </span>
        )}
        <span className="ml-auto text-xs font-mono text-ink-400">
          {card.week_label}
        </span>
      </header>

      <p className="text-xs text-ink-400 mt-0.5">{card.source_name}</p>

      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div>
          <dt className="text-xs text-ink-400">{t('evidenceView.evidenceCard.baseline')}</dt>
          <dd className="font-mono">{card.baseline ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">{t('evidenceView.evidenceCard.current')}</dt>
          <dd className="font-mono">
            {card.current_value === null ? (
              <span className="italic text-ink-400">{t('evidenceView.evidenceCard.notSubmitted')}</span>
            ) : (
              `${card.current_value}${card.unit ? ` ${card.unit}` : ''}`
            )}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-ink-400">{t('evidenceView.evidenceCard.change')}</dt>
          <dd>
            <Delta value={card.change_pct} />
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex items-center gap-2 text-xs">
        <span className="font-semibold">{t(`evidenceCardStatus.${card.status}`)}</span>
        <span className="text-ink-400">·</span>
        <span className="text-ink-600">
          {t('evidenceView.evidenceCard.dataQuality', { quality: card.data_quality })}
        </span>
      </div>

      {card.freshness && (
        <div className="mt-2">
          <FreshnessPill freshness={card.freshness} />
        </div>
      )}

      {card.operational_context && 'reason' in card.operational_context && (
        <div className="mt-2 rounded-md border border-sky-200 bg-sky-50 px-2.5 py-2 text-xs text-sky-900">
          <div className="font-semibold">{t('evidenceView.evidenceCard.operationalContextTitle')}</div>
          <div className="mt-0.5">{card.operational_context.reason}</div>
          <div className="mt-0.5 text-sky-700">
            {card.operational_context.starts_on} → {card.operational_context.ends_on}
          </div>
          <div className="mt-1 text-sky-700">
            {t('evidenceView.evidenceCard.excluded')}
          </div>
        </div>
      )}

      <p className="mt-2 text-xs text-ink-600 leading-relaxed">
        {card.explanation}
      </p>

      <p className="mt-2 text-xs text-ink-400 font-mono">
        {t('evidenceView.evidenceCard.producedBy', { agent: card.produced_by_agent })}
      </p>
    </article>
  )
}

export default function EvidenceView() {
  const { t } = useTranslation('officer')
  const { id } = useParams<{ id: string }>()
  const { data, loading, error, reload } = useAsync<AlertEvidenceResponse>(
    () => api.get(`/alerts/${id}/evidence/`),
    [id],
  )

  if (loading) return <Loading label={t('evidenceView.loading')} />
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
          {t('evidenceView.backToAlert')}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">
            {t('evidenceView.title')}
          </h1>
          <SeverityPill severity={alert.severity} />
        </div>
        <p className="text-sm text-ink-600 mt-1">
          {alert.title} · {alert.cluster} · {alert.week_label}
        </p>
      </div>

      <Card title={t('evidenceView.sourceCard.title', { count: data.evidence.length })}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.evidence.map((card) => (
            <EvidenceCardView key={card.id} card={card} />
          ))}
        </div>
        <p className="text-xs text-ink-400 mt-4">
          {t('evidenceView.sourceCard.footer', { count: why.corroborating_count })}
        </p>
      </Card>

      <EvidenceRelationshipMap relationships={data.relationships} />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={t('evidenceView.crossLevel.title')}>
          <div className="rounded-md border border-violet-200 bg-violet-50 p-3">
            <div className="text-xs font-semibold text-violet-800">
              {t('evidenceView.crossLevel.verdict', { verdict: data.cross_level.verdict.toLowerCase() })}
            </div>
            <p className="text-sm text-violet-900 mt-1 leading-relaxed">
              {data.cross_level.statement}
            </p>
          </div>
          <p className="text-xs text-ink-400 mt-3 leading-relaxed">
            {t('evidenceView.crossLevel.disclaimer')}
          </p>
        </Card>

        <Card title={t('evidenceView.safetyGate.title')}>
          {safety ? (
            <SafetyPanel
              verdict={safety.verdict}
              status={safety.status}
              rules={safety.rules}
              reasons={safety.reasons}
            />
          ) : (
            <p className="text-sm text-ink-400">{t('evidenceView.safetyGate.none')}</p>
          )}
        </Card>
      </div>

      <Card title={t('evidenceView.guidance.title')}>
        <p className="text-xs text-ink-600 -mt-1">
          {t('evidenceView.guidance.description')}
        </p>
        <RagGuidancePanel
          fetcher={() =>
            api.post<RagResponse>('/rag/investigation/', { alert_id: Number(id) })
          }
          deps={[id]}
        />
      </Card>

      <Card
        title={t('evidenceView.agentTrace.title', { count: data.agent_trace.length })}
        action={
          <span className="text-xs text-ink-400">
            {alert.narrative_used_llm
              ? t('evidenceView.agentTrace.llmUsed')
              : t('evidenceView.agentTrace.noLlmUsed')}
          </span>
        }
      >
        <AgentTrace trace={data.agent_trace} />
      </Card>

      <div className="rounded-lg border border-sentinel-200 bg-sentinel-50 px-4 py-3">
        <div className="text-sm font-semibold text-sentinel-700">
          {t('evidenceView.humanReview.title')}
        </div>
        <p className="text-sm text-sentinel-900 mt-1">
          {data.human_review.note}
        </p>
      </div>
    </div>
  )
}
