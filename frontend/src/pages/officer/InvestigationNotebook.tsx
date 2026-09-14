/**
 * Phase 9 — Investigation Notebook.
 *
 * A structured human-decision workspace for one simulation session's
 * current signal (task's own architectural principle, §56: "the officer
 * should visibly remain in control"). Deliberately reuses, rather than
 * rebuilds, everything Phase 4-8 already computed:
 *   - `AgentPipelineView`/`SignalTimelineChart`/`EvidenceConstellation`/
 *     `SourceFusionPanel`/`DataQualityLens`/`WhyAmISeeingThisPanel`/
 *     `SafetyGatePanel` are imported from `SimulationLab.tsx` (exported
 *     there for exactly this reuse) — never re-implemented here.
 *   - Replay (`stepReplay`/`replayIntelligence`) and What-If
 *     (`whatIfResult`) are the SAME Phase 7/8 store state and actions
 *     Simulation Lab already uses — this page never recomputes either.
 *   - `intelligence`/`agentRuns`/`liveStatus` are the same Phase 5/8 store
 *     fields — a live run already in progress keeps updating them exactly
 *     as it does on Simulation Lab; this page only ever *displays* that,
 *     never a second pipeline.
 *
 * The ONLY new data this page reads is `investigation` (Phase 9's own
 * notes/checklist/observations/decision workspace, `useSimulationStore
 * ().investigation`), fetched once on mount via `loadInvestigation`.
 */

import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { Card, Empty, ErrorNote, Loading, SyntheticBadge } from '@/components/ui'
import {
  AgentPipelineView,
  DataQualityLens,
  EvidenceConstellation,
  SafetyGatePanel,
  SignalTimelineChart,
  SourceFusionPanel,
  WhyAmISeeingThisPanel,
} from '@/pages/officer/SimulationLab'
import { useSimulationStore } from '@/store/simulation'
import {
  FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS,
  FEEDBACK_USEFULNESS_LABELS,
  FEEDBACK_YES_NO_LABELS,
  FEEDBACK_YES_PARTIALLY_NO_LABELS,
  INVESTIGATION_DECISION_LABELS,
  type FeedbackEvidenceSufficiency,
  type FeedbackUsefulness,
  type FeedbackYesNo,
  type FeedbackYesPartiallyNo,
  type InvestigationDecisionValue,
} from '@/types'

const SECTIONS = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Signal Timeline' },
  { key: 'evidence', label: 'Evidence Sources' },
  { key: 'contradictions', label: 'Contradictions' },
  { key: 'context', label: 'Community Context' },
  { key: 'notes', label: 'Field Notes' },
  { key: 'checklist', label: 'Verification Checklist' },
  { key: 'decision', label: 'Decision Workspace' },
  { key: 'recommendation', label: 'Final Recommendation' },
  { key: 'feedback', label: 'Feedback & Quality' },
] as const

type SectionKey = (typeof SECTIONS)[number]['key']

const TREND_LABEL: Record<string, string> = {
  NORMAL: 'Normal',
  STABLE: 'Stable',
  INCREASING: 'Increasing',
  SIGNAL_DETECTED: 'Signal Detected',
}

function evidencePillClass(strength: string | null): string {
  switch (strength) {
    case 'STRONG':
      return 'bg-red-100 text-red-700'
    case 'MODERATE':
      return 'bg-amber-100 text-amber-800'
    case 'WEAK':
      return 'bg-ink-100 text-ink-600'
    default:
      return 'bg-ink-100 text-ink-600'
  }
}

function gatePillClass(gate: string | null): string {
  switch (gate) {
    case 'PASS':
      return 'bg-care-100 text-care-700'
    case 'BLOCK':
      return 'bg-red-100 text-red-700'
    case 'INSUFFICIENT':
      return 'bg-amber-100 text-amber-800'
    default:
      return 'bg-ink-100 text-ink-600'
  }
}

/** Section navigation, left column. Also drives Previous/Next in the
 *  bottom bar via shared `investigationSection` store state — task §7:
 *  "one investigation workspace with section navigation", not nine pages. */
function SectionNav() {
  const { investigationSection, setInvestigationSection, investigation } = useSimulationStore()

  return (
    <nav aria-label="Investigation sections" className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">
        Investigation Sections
      </h3>
      <ul className="mt-2 space-y-1">
        {SECTIONS.map((section) => (
          <li key={section.key}>
            <button
              type="button"
              aria-current={investigationSection === section.key ? 'true' : undefined}
              className={`w-full rounded-md px-2.5 py-1.5 text-left text-sm transition ${
                investigationSection === section.key
                  ? 'bg-sentinel-100 font-semibold text-sentinel-700'
                  : 'text-ink-600 hover:bg-ink-50'
              }`}
              onClick={() => setInvestigationSection(section.key)}
            >
              {section.label}
            </button>
          </li>
        ))}
      </ul>
      {investigation && (
        <p className="mt-3 border-t border-ink-200 pt-2 text-[11px] text-ink-400">
          Status: {investigation.status_display}
        </p>
      )}
    </nav>
  )
}

/** Right column — always-visible compact summary (task's own layout
 *  mockup, §6). Reads the SAME `investigation.overview`/`intelligence`
 *  every section already reads; nothing computed twice. */
function InvestigationSummaryPanel() {
  const { investigation, intelligence } = useSimulationStore()
  if (!investigation) return null

  const overview = investigation.overview
  const progress = investigation.checklist.progress

  return (
    <div className="space-y-3 text-xs">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Summary</h3>
      <dl className="space-y-1.5">
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Signal</dt>
          <dd className="font-medium text-ink-800">{overview.primary_signal ?? '—'}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Trend</dt>
          <dd className="font-medium text-ink-800">
            {overview.trend ? TREND_LABEL[overview.trend] ?? overview.trend : '—'}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Evidence</dt>
          <dd>
            <span className={`pill ${evidencePillClass(overview.evidence_strength)}`}>
              {overview.evidence_strength ?? '—'}
            </span>
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Priority</dt>
          <dd className="font-medium text-ink-800">{overview.investigation_priority || '—'}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Safety</dt>
          <dd>
            <span className={`pill ${gatePillClass(overview.safety_gate_result)}`}>
              {overview.safety_gate_result ?? '—'}
            </span>
          </dd>
        </div>
      </dl>
      <div className="border-t border-ink-200 pt-2">
        <div className="flex items-center justify-between text-ink-500">
          <span>Progress</span>
          <span className="font-mono font-semibold text-ink-800">{progress.percent}%</span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
          <div
            className="h-full rounded-full bg-sentinel-500"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
        <p className="mt-1 text-[11px] text-ink-400">
          {progress.checked} / {progress.total} checklist items completed
        </p>
      </div>
      {intelligence?.safety.gate_result === 'BLOCK' && (
        <p className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-800">
          SAFETY BLOCK — escalation is not available for this signal.
        </p>
      )}
    </div>
  )
}

function OverviewSection() {
  const { investigation, intelligence } = useSimulationStore()
  if (!investigation) return null
  const overview = investigation.overview

  return (
    <div className="space-y-4">
      <Card title="Investigation Overview">
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex justify-between">
            <dt className="text-ink-500">Investigation ID</dt>
            <dd className="font-mono">{overview.investigation_id}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Village</dt>
            <dd>{overview.village_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Scenario</dt>
            <dd>{overview.scenario_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Current Week</dt>
            <dd className="font-mono">
              {overview.week} / {overview.total_weeks}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Signal Category</dt>
            <dd>{overview.primary_signal ?? '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Trend</dt>
            <dd>{overview.trend ? TREND_LABEL[overview.trend] ?? overview.trend : '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Evidence Strength</dt>
            <dd>
              <span className={`pill ${evidencePillClass(overview.evidence_strength)}`}>
                {overview.evidence_strength ?? '—'}
              </span>
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Investigation Priority</dt>
            <dd>{overview.investigation_priority || '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">Safety Result</dt>
            <dd>
              <span className={`pill ${gatePillClass(overview.safety_gate_result)}`}>
                {overview.safety_gate_result ?? '—'}
              </span>
            </dd>
          </div>
        </dl>
        <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
          <p>
            <span className="font-medium text-ink-600">Supporting:</span>{' '}
            {overview.sources_supporting.join(', ') || 'none'}
          </p>
          <p>
            <span className="font-medium text-ink-600">Conflicting:</span>{' '}
            {overview.sources_conflicting.join(', ') || 'none'}
          </p>
          <p>
            <span className="font-medium text-ink-600">Insufficient:</span>{' '}
            {overview.sources_insufficient.join(', ') || 'none'}
          </p>
        </div>
      </Card>

      {intelligence && <WhyAmISeeingThisPanel explanation={intelligence.explanation} />}
    </div>
  )
}

/** Reuses the EXISTING Phase 7 Replay mechanism (`stepReplay`/
 *  `replayIntelligence`) to inspect a historical week — never mutates
 *  `session.replay_position`, never recomputes anything (task §31). */
function TimelineSection() {
  const {
    intelligence,
    replayWeek,
    replayIntelligence,
    replayLoading,
    stepReplay,
    exitReplay,
  } = useSimulationStore()

  if (!intelligence) {
    return <Empty>No reporting weeks are available yet for this session.</Empty>
  }

  const viewing = replayWeek !== null ? replayIntelligence : intelligence

  return (
    <div className="space-y-4">
      <Card title="Signal Timeline">
        <SignalTimelineChart timeline={intelligence.timeline} />
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-500">Inspect a week:</span>
          {intelligence.timeline.map((point) => (
            <button
              key={point.week}
              type="button"
              disabled={replayLoading}
              className={`pill ${
                replayWeek === point.week
                  ? 'bg-sentinel-100 text-sentinel-700'
                  : 'bg-ink-100 text-ink-600'
              }`}
              onClick={() => void stepReplay(point.week)}
            >
              W{point.week}
            </button>
          ))}
          {replayWeek !== null && (
            <button type="button" className="pill bg-ink-100 text-ink-600" onClick={exitReplay}>
              Back to current
            </button>
          )}
        </div>
        {replayWeek !== null && (
          <p className="mt-2 text-xs text-amber-800">
            ◷ Viewing historical week {replayWeek} — read-only replay, nothing changes.
          </p>
        )}
      </Card>

      {viewing && (
        <Card title="Source Evolution">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-ink-500">
                <th className="py-1 pr-2 font-medium">Source</th>
                <th className="py-1 pr-2 font-medium">Value</th>
                <th className="py-1 font-medium">Reported</th>
              </tr>
            </thead>
            <tbody>
              {viewing.source_fusion.map((entry) => (
                <tr key={entry.source} className="border-t border-ink-100">
                  <td className="py-1 pr-2">{entry.source}</td>
                  <td className="py-1 pr-2 font-mono">
                    {entry.current_value === null ? '—' : entry.current_value}
                  </td>
                  <td className="py-1">
                    {entry.reported === false ? (
                      <span className="text-ink-400">Not reported</span>
                    ) : (
                      'Reported'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

/** Task §34 "Multi-Agent Transparency": expose how this week's
 *  intelligence was produced — the SAME `agentRuns` Simulation Lab's own
 *  `AgentPipelineView` already renders (Phase 4/8), never a second
 *  execution trace. */
function PipelineTransparencyCard() {
  const { agentRuns, pipelineError } = useSimulationStore()
  if (!agentRuns.length) return null

  return (
    <Card title="How This Intelligence Was Produced">
      <AgentPipelineView agentRuns={agentRuns} pipelineError={pipelineError} />
    </Card>
  )
}

function EvidenceSection() {
  const { intelligence, replayWeek, replayIntelligence } = useSimulationStore()
  const viewing = replayWeek !== null ? replayIntelligence : intelligence
  if (!viewing) return <Empty>No evidence available yet for this session.</Empty>

  return (
    <div className="space-y-4">
      <PipelineTransparencyCard />
      <EvidenceConstellation
        constellation={viewing.constellation}
        primarySignal={
          viewing.timeline.length ? viewing.timeline[viewing.timeline.length - 1].primary_signal : null
        }
      />
      <SourceFusionPanel sourceFusion={viewing.source_fusion} />
      <DataQualityLens dataQuality={viewing.data_quality} />
      <SafetyGatePanel safety={viewing.safety} />
    </div>
  )
}

function ContradictionsSection() {
  const { investigation } = useSimulationStore()
  if (!investigation) return null
  const { contradictions } = investigation

  if (!contradictions.length) {
    return (
      <Card title="Contradictions">
        <Empty>No conflicting source relationship detected.</Empty>
      </Card>
    )
  }

  return (
    <Card title="Contradiction Inspector">
      <div className="space-y-3">
        {contradictions.map((entry) => (
          <div key={entry.source} className="rounded-md border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-ink-800">{entry.source}</span>
              <span className="pill bg-amber-100 text-amber-800">{entry.relation}</span>
            </div>
            <p className="mt-1 text-xs text-ink-700">{entry.reason}</p>
            <p className="mt-2 text-[11px] font-medium uppercase tracking-wide text-ink-500">
              Suggested verification
            </p>
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-ink-600">
              {entry.suggested_verification.map((prompt) => (
                <li key={prompt}>{prompt}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Card>
  )
}

function CommunityContextSection() {
  const { investigation } = useSimulationStore()
  if (!investigation) return null
  const entries = investigation.community_context

  return (
    <Card title="Community Context">
      {entries.length === 0 ? (
        <Empty>No synthetic community context recorded for this scenario.</Empty>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry, index) => (
            <li key={index} className="rounded-md border border-ink-200 bg-ink-50 p-2.5 text-sm">
              <span className="pill bg-ink-100 text-ink-600 text-[10px] font-medium">
                SYNTHETIC SIMULATION CONTEXT
              </span>
              <p className="mt-1 text-ink-700">
                Week {entry.week}: {entry.note}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

function FieldNotesSection() {
  const {
    investigation,
    investigationSaving,
    addInvestigationObservation,
    saveInvestigationNotes,
  } = useSimulationStore()
  const [draftWeek, setDraftWeek] = useState('')
  const [draftSource, setDraftSource] = useState('')
  const [draftNotes, setDraftNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  if (!investigation) return null

  async function handleAddObservation() {
    setSubmitError(null)
    const week = Number(draftWeek)
    if (!week || !draftSource.trim() || !draftNotes.trim()) {
      setSubmitError('Week, source, and notes are all required.')
      return
    }
    setSubmitting(true)
    try {
      await addInvestigationObservation({ week, source: draftSource.trim(), notes: draftNotes.trim() })
      setDraftWeek('')
      setDraftSource('')
      setDraftNotes('')
    } catch {
      setSubmitError('Unable to save this observation.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Investigation Notes">
        <textarea
          className="input min-h-[140px] w-full"
          placeholder="General notes, signal interpretation, data inconsistencies, community observations, verification notes, recommendation notes…"
          defaultValue={investigation.notes}
          onChange={(event) => saveInvestigationNotes(event.target.value)}
        />
        <p className="mt-1 text-[11px] text-ink-400">
          {investigationSaving ? 'Saving…' : 'Saved automatically as you type.'}
        </p>
      </Card>

      <Card title="Simulated Field Observations">
        {investigation.observations.length === 0 ? (
          <Empty>No simulated field observations recorded.</Empty>
        ) : (
          <ul className="mb-3 space-y-2">
            {investigation.observations.map((obs) => (
              <li key={obs.id} className="rounded-md border border-ink-200 p-2.5 text-sm">
                <div className="flex items-center justify-between text-xs text-ink-500">
                  <span>
                    Week {obs.week} · {obs.source}
                  </span>
                  <span className="pill bg-ink-100 text-ink-600 text-[10px] font-medium">
                    SIMULATED FIELD OBSERVATION
                  </span>
                </div>
                <p className="mt-1 text-ink-700">{obs.notes}</p>
              </li>
            ))}
          </ul>
        )}

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-[5rem_8rem_1fr_auto]">
          <input
            className="input"
            placeholder="Week"
            inputMode="numeric"
            value={draftWeek}
            onChange={(event) => setDraftWeek(event.target.value)}
          />
          <input
            className="input"
            placeholder="Source (e.g. CHW)"
            value={draftSource}
            onChange={(event) => setDraftSource(event.target.value)}
          />
          <input
            className="input"
            placeholder="Observation notes"
            value={draftNotes}
            onChange={(event) => setDraftNotes(event.target.value)}
          />
          <button
            type="button"
            className="btn-sentinel py-1.5 text-xs"
            disabled={submitting}
            onClick={() => void handleAddObservation()}
          >
            Add
          </button>
        </div>
        {submitError && <p className="mt-2 text-xs text-red-700">{submitError}</p>}
      </Card>
    </div>
  )
}

function ChecklistSection() {
  const { investigation, investigationSaving, updateInvestigationChecklist } = useSimulationStore()
  if (!investigation) return null
  const { items, values, progress } = investigation.checklist

  return (
    <Card title="Verification Checklist">
      <p className="text-xs text-ink-500">
        {progress.checked} / {progress.total} completed — Investigation Progress: {progress.percent}%
      </p>
      <ul className="mt-3 space-y-1.5">
        {items.map((item) => (
          <li key={item.key}>
            <label className="flex items-center gap-2 text-sm text-ink-700">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-ink-300"
                checked={Boolean(values[item.key])}
                disabled={investigationSaving}
                onChange={(event) =>
                  void updateInvestigationChecklist({ [item.key]: event.target.checked })
                }
              />
              {item.label}
            </label>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function WhatIfComparisonCard() {
  const { whatIfResult } = useSimulationStore()
  if (!whatIfResult) {
    return (
      <Card title="What-If Comparison">
        <Empty>No hypothetical comparison has been run yet — run one from Simulation Lab.</Empty>
      </Card>
    )
  }

  return (
    <Card title="What-If Comparison">
      <p className="pill bg-ink-100 text-ink-600 font-semibold">HYPOTHETICAL</p>
      <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-ink-500">Evidence Strength</dt>
          <dd className="mt-0.5">
            Original: {whatIfResult.original.evidence_strength ?? '—'}
            <br />
            What-If: {whatIfResult.hypothetical.safety.evidence_strength ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-ink-500">Safety</dt>
          <dd className="mt-0.5">
            Original: {whatIfResult.original.gate_result ?? '—'}
            <br />
            What-If: {whatIfResult.hypothetical.safety.gate_result ?? '—'}
          </dd>
        </div>
        <div>
          <dt className="text-ink-500">Changed sources</dt>
          <dd className="mt-0.5">{whatIfResult.changed_sources.join(', ') || 'none'}</dd>
        </div>
      </dl>
    </Card>
  )
}

function DecisionSection() {
  const { investigation, intelligence, investigationDecisionSaving, recordInvestigationDecision } =
    useSimulationStore()
  const [reason, setReason] = useState('')
  const [decisionError, setDecisionError] = useState<string | null>(null)

  if (!investigation || !intelligence) return null

  const blocked = intelligence.safety.gate_result === 'BLOCK'
  const suggested = investigation.suggested_decision

  async function handleDecide(decision: InvestigationDecisionValue) {
    setDecisionError(null)
    try {
      await recordInvestigationDecision(decision, reason)
    } catch {
      setDecisionError('Unable to record this decision. Please try again.')
    }
  }

  return (
    <div className="space-y-4">
      <Card title="Evidence Summary">
        <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-ink-500">Evidence</dt>
            <dd className="font-medium">{intelligence.explanation.evidence_strength}</dd>
          </div>
          <div>
            <dt className="text-ink-500">Safety</dt>
            <dd className="font-medium">{intelligence.safety.gate_result ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-ink-500">Data Quality</dt>
            <dd className="font-medium">{intelligence.data_quality.completeness_pct}%</dd>
          </div>
          <div>
            <dt className="text-ink-500">Checklist</dt>
            <dd className="font-medium">{investigation.checklist.progress.percent}%</dd>
          </div>
        </dl>
      </Card>

      <WhatIfComparisonCard />

      <Card title="Decision Workspace">
        <p className="pill bg-ink-100 text-ink-600 font-semibold">SYSTEM INTELLIGENCE</p>
        <p className="mt-2 text-sm text-ink-700">{intelligence.explanation.routed_reason}</p>

        {blocked ? (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p className="font-semibold">SAFETY BLOCK</p>
            <p className="mt-1">
              This investigation cannot be finalized while the Safety Gate result is BLOCK. Review
              the Safety Gate section to see what failed, and resolve it before recording a decision.
            </p>
          </div>
        ) : (
          <>
            {suggested && (
              <p className="mt-3 rounded-md border border-sentinel-200 bg-sentinel-50 px-3 py-2 text-xs text-sentinel-800">
                System Suggested Next Step: <strong>{INVESTIGATION_DECISION_LABELS[suggested]}</strong>{' '}
                — a suggestion only; you choose the final decision.
              </p>
            )}

            <p className="mt-4 pill bg-ink-800 text-white font-semibold">OFFICER DECISION</p>
            <textarea
              className="input mt-2 w-full"
              rows={2}
              placeholder="Optional reason for this decision…"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {(Object.keys(INVESTIGATION_DECISION_LABELS) as InvestigationDecisionValue[]).map(
                (decision) => (
                  <button
                    key={decision}
                    type="button"
                    disabled={investigationDecisionSaving}
                    className={`btn-ghost py-1.5 text-xs ${
                      investigation.decision.value === decision
                        ? 'border-sentinel-400 bg-sentinel-50 text-sentinel-700'
                        : ''
                    }`}
                    onClick={() => void handleDecide(decision)}
                  >
                    {INVESTIGATION_DECISION_LABELS[decision]}
                  </button>
                ),
              )}
            </div>
            {decisionError && <p className="mt-2 text-xs text-red-700">{decisionError}</p>}
          </>
        )}

        {investigation.decision.value && (
          <p className="mt-4 rounded-md border border-care-200 bg-care-50 px-3 py-2 text-xs text-care-800">
            Recorded: <strong>{investigation.decision.value_display}</strong> by{' '}
            {investigation.decision.decided_by ?? '—'}
            {investigation.decision.decided_at &&
              ` on ${new Date(investigation.decision.decided_at).toLocaleString()}`}
            .
          </p>
        )}
      </Card>
    </div>
  )
}

function RecommendationSection() {
  const { intelligence, investigation } = useSimulationStore()
  if (!intelligence || !investigation) return null

  return (
    <Card title="Final Recommendation">
      <p className="text-sm text-ink-700">{intelligence.explanation.suggested_verification}</p>
      {investigation.decision.value ? (
        <p className="mt-3 text-sm text-ink-800">
          <span className="font-medium">Officer decision:</span>{' '}
          {investigation.decision.value_display}
          {investigation.decision.reason && ` — ${investigation.decision.reason}`}
        </p>
      ) : (
        <p className="mt-3 text-xs text-ink-400">
          No decision has been recorded yet — see the Decision Workspace section.
        </p>
      )}
      <p className="mt-3 text-[11px] text-ink-400">
        Decision support only — this is an evidence-grounded suggestion, never an autonomous action.
      </p>
    </Card>
  )
}

/**
 * Phase 10 — Officer Feedback (task §10/§29). Describes the officer's own
 * EXPERIENCE ("Officer assessment" / "Simulation evaluation"), never
 * ground truth — and, structurally, can never touch the decision/
 * evidence/safety this page already shows: `saveFeedback` only ever
 * calls `PATCH .../investigation/feedback/`, a separate row entirely
 * from `SimulationInvestigation`/`SimulationResult` (task §41-§43).
 */
function FeedbackChoiceGroup<T extends string>({
  label,
  options,
  labels,
  value,
  disabled,
  onSelect,
}: {
  label: string
  options: readonly T[]
  labels: Record<T, string>
  value: T | ''
  disabled: boolean
  onSelect: (option: T) => void
}) {
  return (
    <div className="mt-3">
      <p className="text-xs font-medium text-ink-600">{label}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            disabled={disabled}
            className={`pill ${
              value === option
                ? 'bg-sentinel-100 font-semibold text-sentinel-700'
                : 'bg-ink-100 text-ink-600'
            }`}
            onClick={() => onSelect(option)}
          >
            {labels[option]}
          </button>
        ))}
      </div>
    </div>
  )
}

function FeedbackSection() {
  const { feedback, feedbackLoading, feedbackSaving, feedbackError, saveFeedback } = useSimulationStore()
  const [comment, setComment] = useState(feedback?.comment ?? '')
  const [justSaved, setJustSaved] = useState(false)

  useEffect(() => {
    setComment(feedback?.comment ?? '')
  }, [feedback?.comment])

  if (feedbackLoading && !feedback) return <Loading label="Loading feedback…" />

  async function handleFeedbackChange(patch: Parameters<typeof saveFeedback>[0]) {
    setJustSaved(false)
    try {
      await saveFeedback(patch)
      setJustSaved(true)
    } catch {
      // feedbackError is already surfaced below by the store.
    }
  }

  return (
    <Card title="Officer Feedback">
      <p className="pill bg-ink-100 text-ink-600 font-semibold">SIMULATION EVALUATION</p>
      <p className="mt-2 text-xs text-ink-500">
        This describes your own experience investigating this signal — not a verdict on whether it
        was medically correct. It never changes the recorded decision, evidence, or safety result.
      </p>

      <FeedbackChoiceGroup
        label="How useful was this signal?"
        options={['VERY_USEFUL', 'USEFUL', 'PARTIALLY_USEFUL', 'NOT_USEFUL'] as const}
        labels={FEEDBACK_USEFULNESS_LABELS}
        value={feedback?.usefulness ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackUsefulness) => void handleFeedbackChange({ usefulness: value })}
      />
      <FeedbackChoiceGroup
        label="Evidence sufficiency"
        options={['SUFFICIENT', 'PARTIALLY_SUFFICIENT', 'INSUFFICIENT'] as const}
        labels={FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS}
        value={feedback?.evidence_sufficiency ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackEvidenceSufficiency) =>
          void handleFeedbackChange({ evidence_sufficiency: value })
        }
      />
      <FeedbackChoiceGroup
        label="Was the suggested next step helpful?"
        options={['YES', 'PARTIALLY', 'NO'] as const}
        labels={FEEDBACK_YES_PARTIALLY_NO_LABELS}
        value={feedback?.recommendation_helpful ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackYesPartiallyNo) =>
          void handleFeedbackChange({ recommendation_helpful: value })
        }
      />
      <FeedbackChoiceGroup
        label="Additional verification required?"
        options={['YES', 'NO'] as const}
        labels={FEEDBACK_YES_NO_LABELS}
        value={feedback?.additional_verification_required ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackYesNo) =>
          void handleFeedbackChange({ additional_verification_required: value })
        }
      />

      <div className="mt-4 border-t border-ink-200 pt-3">
        <p className="text-xs font-medium text-ink-600">Comment (optional)</p>
        <textarea
          className="input mt-1.5 w-full"
          rows={2}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
        <div className="mt-2 flex items-center gap-2">
          <button
            type="button"
            className="btn-ghost py-1.5 text-xs"
            disabled={feedbackSaving}
            onClick={() => void handleFeedbackChange({ comment })}
          >
            Save Feedback
          </button>
          {justSaved && !feedbackSaving && (
            <span className="text-xs text-care-700">Feedback saved ✓</span>
          )}
        </div>
      </div>

      {feedbackError && (
        <div className="mt-2">
          <ErrorNote message={feedbackError} />
        </div>
      )}
    </Card>
  )
}

const SECTION_CONTENT: Record<SectionKey, () => React.JSX.Element | null> = {
  overview: OverviewSection,
  timeline: TimelineSection,
  evidence: EvidenceSection,
  contradictions: ContradictionsSection,
  context: CommunityContextSection,
  notes: FieldNotesSection,
  checklist: ChecklistSection,
  decision: DecisionSection,
  recommendation: RecommendationSection,
  feedback: FeedbackSection,
}

/** A quiet, non-intrusive banner — task §33: Phase 8 live updates must
 *  never silently modify notes/decisions, only inform. */
function LiveUpdateBanner() {
  const { liveStatus, liveWeek, sessionId, loadInvestigation } = useSimulationStore()
  const [dismissedWeek, setDismissedWeek] = useState<number | null>(null)
  const lastSeenWeek = useRef<number | null>(null)

  useEffect(() => {
    if (lastSeenWeek.current === null) lastSeenWeek.current = liveWeek
  }, [liveWeek])

  if (liveStatus === 'IDLE' || liveWeek === null) return null
  if (lastSeenWeek.current !== null && liveWeek <= lastSeenWeek.current) return null
  if (dismissedWeek === liveWeek) return null

  return (
    <div className="card mb-3 flex items-center justify-between gap-3 border border-sentinel-200 bg-sentinel-50 px-4 py-2.5 text-sm text-sentinel-800">
      <span>NEW SIGNAL DATA AVAILABLE — Week {liveWeek} completed. Evidence and safety updated.</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn-ghost py-1 text-xs"
          onClick={() => {
            if (sessionId) void loadInvestigation(sessionId)
            lastSeenWeek.current = liveWeek
          }}
        >
          Refresh Investigation Context
        </button>
        <button
          type="button"
          className="text-xs text-sentinel-600 underline"
          onClick={() => setDismissedWeek(liveWeek)}
        >
          Dismiss
        </button>
      </div>
    </div>
  )
}

export default function InvestigationNotebookPage() {
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const sessionId = Number(sessionIdParam)

  const {
    investigation,
    investigationLoading,
    investigationError,
    investigationSection,
    setInvestigationSection,
    investigationReportLoading,
    exportInvestigationReport,
    loadInvestigation,
    loadFeedback,
    activeSession,
  } = useSimulationStore()

  useEffect(() => {
    if (Number.isFinite(sessionId)) {
      void loadInvestigation(sessionId)
      void loadFeedback(sessionId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  if (!Number.isFinite(sessionId)) {
    return <ErrorNote message="This investigation link is invalid." />
  }

  if (investigationLoading && !investigation) {
    return <Loading label="Loading investigation…" />
  }

  if (investigationError && !investigation) {
    return <ErrorNote message={investigationError} onRetry={() => void loadInvestigation(sessionId)} />
  }

  if (!investigation) {
    return (
      <Empty>
        Open this investigation from the Simulation Lab to load it here.
      </Empty>
    )
  }

  const currentIndex = SECTIONS.findIndex((section) => section.key === investigationSection)
  const SectionComponent = SECTION_CONTENT[investigationSection as SectionKey] ?? OverviewSection

  return (
    <div className="flex flex-col gap-3">
      <div className="card flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-ink-800">Investigation Notebook</p>
          <p className="text-xs text-ink-500">
            {investigation.overview.village_name} · Week {investigation.overview.week}
          </p>
        </div>
        <SyntheticBadge />
      </div>

      <LiveUpdateBanner />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(200px,20%)_1fr_minmax(220px,23%)]">
        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Investigation navigation"
        >
          <SectionNav />
        </aside>

        <main
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Investigation content"
        >
          <SectionComponent />
        </main>

        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Investigation summary"
        >
          <InvestigationSummaryPanel />
        </aside>
      </div>

      <div
        className="card sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 px-4 py-3"
        role="toolbar"
        aria-label="Investigation navigation controls"
      >
        <button
          type="button"
          className="btn-ghost py-1.5"
          onClick={() => navigate(activeSession ? '/officer/simulation' : '/officer/simulation')}
        >
          ◀ Back to Simulation
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-ghost py-1.5"
            disabled={currentIndex <= 0}
            onClick={() => setInvestigationSection(SECTIONS[Math.max(0, currentIndex - 1)].key)}
          >
            ◀ Previous
          </button>
          <button
            type="button"
            className="btn-ghost py-1.5"
            disabled={currentIndex >= SECTIONS.length - 1}
            onClick={() =>
              setInvestigationSection(SECTIONS[Math.min(SECTIONS.length - 1, currentIndex + 1)].key)
            }
          >
            Next Section ▶
          </button>
        </div>
        <button
          type="button"
          className="btn-sentinel py-1.5"
          disabled={investigationReportLoading}
          onClick={() => void exportInvestigationReport()}
        >
          {investigationReportLoading ? 'Generating…' : 'Export Report'}
        </button>
      </div>

      <p className="text-xs text-ink-400">
        Synthetic simulation only — not real surveillance data. The system organizes evidence and
        suggests verification steps; the Health Officer makes every final decision.
      </p>
    </div>
  )
}
