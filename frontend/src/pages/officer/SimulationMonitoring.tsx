/**
 * Phase 10 — Intelligence Quality Monitoring.
 *
 * A read-only observability dashboard over already-persisted simulation
 * data (`GET /api/simulation/monitoring/`, entirely backend-aggregated —
 * this page never counts raw records itself). Village-scoped by the
 * authenticated officer's own account, exactly like every other page in
 * this portal — there is no village selector here either.
 *
 * This is explicitly NOT a real-world epidemiological surveillance
 * dashboard, an "AI model dashboard", or a quality score: every metric is
 * a plain count/percentage of something Phase 4-9 already computed and
 * persisted (task §44: "avoid AI score, AI confidence, accuracy
 * percentage"). Feedback is framed throughout as the officer's own
 * experience, never ground truth.
 */

import { useEffect } from 'react'

import { Card, Empty, ErrorNote, Loading, SyntheticBadge } from '@/components/ui'
import { useSimulationStore } from '@/store/simulation'
import {
  FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS,
  FEEDBACK_USEFULNESS_LABELS,
  INVESTIGATION_DECISION_LABELS,
  type FeedbackUsefulness,
  type InvestigationDecisionValue,
  type MonitoringRatio,
} from '@/types'

function RatioCaption({ ratio }: { ratio: MonitoringRatio }) {
  if (ratio.denominator === 0) {
    return <p className="text-xs text-ink-400">No observations yet</p>
  }
  return (
    <p className="text-xs text-ink-500">
      {ratio.numerator} / {ratio.denominator} · {ratio.percentage}%
      {ratio.limited_sample && <span className="ml-1 text-amber-700">Limited sample</span>}
    </p>
  )
}

function MetricCard({
  label,
  value,
  caption,
}: {
  label: string
  value: React.ReactNode
  caption?: React.ReactNode
}) {
  return (
    <div className="rounded-lg border border-ink-200 bg-white p-3">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500">{label}</p>
      <p className="mt-1 font-mono text-2xl font-semibold text-ink-800">{value}</p>
      {caption}
    </div>
  )
}

function UsefulnessBars() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null
  const options: FeedbackUsefulness[] = ['VERY_USEFUL', 'USEFUL', 'PARTIALLY_USEFUL', 'NOT_USEFUL']
  const total = monitoring.feedback.submitted

  return (
    <Card title="Alert Usefulness — Officer Assessment">
      {total === 0 ? (
        <Empty>No feedback submitted yet.</Empty>
      ) : (
        <div className="space-y-2">
          {options.map((option) => {
            const ratio = monitoring.feedback.usefulness[option]
            return (
              <div key={option}>
                <div className="flex items-center justify-between text-xs text-ink-600">
                  <span>{FEEDBACK_USEFULNESS_LABELS[option]}</span>
                  <span className="font-mono">
                    {ratio.numerator} / {ratio.denominator}
                    {ratio.percentage !== null && ` · ${ratio.percentage}%`}
                  </span>
                </div>
                <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-ink-100">
                  <div
                    className="h-full rounded-full bg-sentinel-500"
                    style={{ width: `${ratio.percentage ?? 0}%` }}
                  />
                </div>
              </div>
            )
          })}
          {monitoring.feedback.response_rate.limited_sample && (
            <p className="mt-1 text-xs text-amber-700">
              Limited sample — collect more feedback before interpreting this trend.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

function EvidenceQualityCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null
  const { evidence } = monitoring

  return (
    <Card title="Evidence Quality">
      {evidence.total === 0 ? (
        <Empty>No completed weeks yet.</Empty>
      ) : (
        <dl className="space-y-1.5 text-sm">
          <div className="flex justify-between">
            <dt className="text-ink-500">Strong</dt>
            <dd className="font-mono font-medium">{evidence.STRONG}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Moderate</dt>
            <dd className="font-mono font-medium">{evidence.MODERATE}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Weak</dt>
            <dd className="font-mono font-medium">{evidence.WEAK}</dd>
          </div>
        </dl>
      )}
      <div className="mt-3 border-t border-ink-200 pt-2 text-xs text-ink-500">
        <p className="font-medium text-ink-600">Feedback: Evidence Sufficiency</p>
        {(['SUFFICIENT', 'PARTIALLY_SUFFICIENT', 'INSUFFICIENT'] as const).map((value) => (
          <div key={value} className="mt-1 flex justify-between">
            <span>{FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS[value]}</span>
            <RatioCaption ratio={monitoring.feedback.evidence_sufficiency[value]} />
          </div>
        ))}
      </div>
    </Card>
  )
}

function InvestigationOutcomesCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null
  const entries = Object.entries(monitoring.decisions) as [InvestigationDecisionValue, number][]
  const hasAny = entries.some(([, count]) => count > 0)

  return (
    <Card title="Investigation Outcomes">
      {!hasAny ? (
        <Empty>No decisions recorded yet.</Empty>
      ) : (
        <ul className="space-y-1.5 text-sm">
          {entries
            .filter(([, count]) => count > 0)
            .map(([decision, count]) => (
              <li key={decision} className="flex justify-between">
                <span className="text-ink-600">{INVESTIGATION_DECISION_LABELS[decision]}</span>
                <span className="font-mono font-medium">{count}</span>
              </li>
            ))}
        </ul>
      )}
      <div className="mt-3 border-t border-ink-200 pt-2 text-xs text-ink-500">
        <p className="font-medium text-ink-600">Human Decision Alignment</p>
        <p className="mt-1">
          {monitoring.decision_alignment.aligned} aligned with the system suggestion,{' '}
          {monitoring.decision_alignment.differed} differed
          {monitoring.decision_alignment.no_suggestion > 0 &&
            `, ${monitoring.decision_alignment.no_suggestion} had no suggestion`}
          .
        </p>
        <p className="mt-1 text-[11px] text-ink-400">
          A human decision differing from the suggestion is not an error — it is the officer's own
          judgement.
        </p>
      </div>
    </Card>
  )
}

function SafetyCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null
  const { safety } = monitoring

  return (
    <Card title="Safety Outcomes">
      <dl className="grid grid-cols-3 gap-2 text-center text-sm">
        <div className="rounded-md bg-care-50 py-2">
          <dt className="text-[11px] text-ink-500">PASS</dt>
          <dd className="font-mono text-lg font-semibold text-care-700">{safety.PASS}</dd>
        </div>
        <div className="rounded-md bg-amber-50 py-2">
          <dt className="text-[11px] text-ink-500">INSUFFICIENT</dt>
          <dd className="font-mono text-lg font-semibold text-amber-800">{safety.INSUFFICIENT}</dd>
        </div>
        <div className="rounded-md bg-red-50 py-2">
          <dt className="text-[11px] text-ink-500">BLOCK</dt>
          <dd className="font-mono text-lg font-semibold text-red-700">{safety.BLOCK}</dd>
        </div>
      </dl>
      <p className="mt-3 text-[11px] text-ink-400">
        Safety blocks are hard gates and cannot be overridden by feedback.
      </p>
    </Card>
  )
}

function SourceAgreementCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null

  return (
    <Card title="Source Relationship Monitoring">
      {monitoring.source_relationships.length === 0 ? (
        <Empty>No correlation data available yet.</Empty>
      ) : (
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-ink-500">
              <th className="py-1 pr-2 font-medium">Source</th>
              <th className="py-1 pr-2 font-medium">Supporting</th>
              <th className="py-1 pr-2 font-medium">Conflicting</th>
              <th className="py-1 font-medium">Insufficient</th>
            </tr>
          </thead>
          <tbody>
            {monitoring.source_relationships.map((entry) => (
              <tr key={entry.source} className="border-t border-ink-100">
                <td className="py-1 pr-2 font-medium text-ink-700">{entry.source}</td>
                <td className="py-1 pr-2 font-mono">{entry.SUPPORTING}</td>
                <td className="py-1 pr-2 font-mono">{entry.CONFLICTING}</td>
                <td className="py-1 font-mono">{entry.INSUFFICIENT}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-[11px] text-ink-400">
        Counts reflect each source's relationship to that week's primary signal — not a claim about
        why sources agree or disagree.
      </p>
    </Card>
  )
}

const ACTIVITY_LABEL: Record<string, string> = {
  investigation_started: 'Investigation started',
  notes_updated: 'Notes updated',
  checklist_updated: 'Checklist updated',
  decision_recorded: 'Decision recorded',
  feedback_submitted: 'Feedback submitted',
  feedback_updated: 'Feedback updated',
  observation_added: 'Field observation added',
  report_exported: 'Report exported',
}

function RecentActivityCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null

  return (
    <Card title="Recent Investigation Activity">
      {monitoring.recent_activity.length === 0 ? (
        <Empty>No investigation activity recorded yet.</Empty>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {monitoring.recent_activity.map((entry, index) => (
            <li key={index} className="flex items-center justify-between border-b border-ink-100 pb-1.5">
              <span className="text-ink-700">
                {ACTIVITY_LABEL[entry.event_type] ?? entry.event_type} — investigation #
                {entry.investigation_id}
              </span>
              <span className="text-ink-400">{new Date(entry.timestamp).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function QualityObservationsCard() {
  const { monitoring } = useSimulationStore()
  if (!monitoring) return null

  return (
    <Card title="Quality Observations">
      {monitoring.quality_observations.length === 0 ? (
        <Empty>No quality observations at this time.</Empty>
      ) : (
        <ul className="list-disc space-y-1 pl-4 text-sm text-ink-700">
          {monitoring.quality_observations.map((observation, index) => (
            <li key={index}>{observation}</li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-ink-400">
        These are monitoring observations and suggested reviews — feedback indicates an opportunity
        for future human review, and never automatically changes system behavior.
      </p>
    </Card>
  )
}

export default function SimulationMonitoringPage() {
  const { monitoring, monitoringLoading, monitoringError, loadMonitoring } = useSimulationStore()

  useEffect(() => {
    void loadMonitoring()
  }, [loadMonitoring])

  if (monitoringLoading && !monitoring) {
    return <Loading label="Loading Intelligence Monitoring…" />
  }

  if (monitoringError && !monitoring) {
    return <ErrorNote message={monitoringError} onRetry={() => void loadMonitoring()} />
  }

  if (!monitoring) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="card flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-ink-800">Intelligence Monitoring</p>
          <p className="text-xs text-ink-500">{monitoring.scope.village_name}</p>
        </div>
        <SyntheticBadge />
      </div>
      <p className="text-xs text-ink-400">
        Synthetic simulation demonstration data — not real surveillance. This monitors the quality of
        the simulator and officer feedback, not real-world epidemiology.
      </p>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <MetricCard label="Signals" value={monitoring.sessions.total} caption={
          <p className="text-xs text-ink-500">{monitoring.sessions.completed} completed</p>
        } />
        <MetricCard
          label="Investigations"
          value={monitoring.investigations.started}
          caption={<RatioCaption ratio={monitoring.investigations.decision_rate} />}
        />
        <MetricCard
          label="Feedback Response"
          value={monitoring.feedback.submitted}
          caption={<RatioCaption ratio={monitoring.feedback.response_rate} />}
        />
        <MetricCard
          label="Evidence Sufficiency"
          value={`${monitoring.feedback.evidence_sufficiency.SUFFICIENT.percentage ?? '—'}%`}
          caption={<RatioCaption ratio={monitoring.feedback.evidence_sufficiency.SUFFICIENT} />}
        />
        <MetricCard label="Safety Blocks" value={monitoring.safety.BLOCK} caption={
          <p className="text-xs text-ink-500">of {monitoring.safety.total} evaluated</p>
        } />
        <MetricCard
          label="Human Decisions"
          value={monitoring.investigations.decisions_recorded}
          caption={<p className="text-xs text-ink-500">recorded by officers</p>}
        />
      </div>

      <UsefulnessBars />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <EvidenceQualityCard />
        <InvestigationOutcomesCard />
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <SafetyCard />
        <SourceAgreementCard />
      </div>

      <QualityObservationsCard />
      <RecentActivityCard />
    </div>
  )
}
