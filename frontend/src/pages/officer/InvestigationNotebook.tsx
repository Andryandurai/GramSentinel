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
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')

  return (
    <nav aria-label={t('notebook.nav.heading')} className="space-y-1">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">
        {t('notebook.nav.heading')}
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
              {t(`notebook.sections.${section.key}`)}
            </button>
          </li>
        ))}
      </ul>
      {investigation && (
        <p className="mt-3 border-t border-ink-200 pt-2 text-[11px] text-ink-400">
          {t('notebook.nav.statusLine', {
            status: tc(`status.${investigation.status}`, {
              defaultValue: t(`agentRunStatus.${investigation.status}`, {
                defaultValue: investigation.status_display,
              }),
            }),
          })}
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
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')
  if (!investigation) return null

  const overview = investigation.overview
  const progress = investigation.checklist.progress

  return (
    <div className="space-y-3 text-xs">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">
        {t('notebook.summary.heading')}
      </h3>
      <dl className="space-y-1.5">
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">{t('notebook.summary.signal')}</dt>
          <dd className="font-medium text-ink-800">{overview.primary_signal ?? '—'}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">{t('notebook.summary.trend')}</dt>
          <dd className="font-medium text-ink-800">
            {overview.trend ? t(`trend.${overview.trend}`, { defaultValue: overview.trend }) : '—'}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">{t('notebook.summary.evidence')}</dt>
          <dd>
            <span className={`pill ${evidencePillClass(overview.evidence_strength)}`}>
              {overview.evidence_strength
                ? t(`evidenceStrength.${overview.evidence_strength}`, {
                    defaultValue: overview.evidence_strength,
                  })
                : '—'}
            </span>
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">{t('notebook.summary.priority')}</dt>
          <dd className="font-medium text-ink-800">
            {overview.investigation_priority
              ? tc(`status.${overview.investigation_priority}`, {
                  defaultValue: overview.investigation_priority,
                })
              : '—'}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">{t('notebook.summary.safety')}</dt>
          <dd>
            <span className={`pill ${gatePillClass(overview.safety_gate_result)}`}>
              {overview.safety_gate_result
                ? tc(`status.${overview.safety_gate_result}`, { defaultValue: overview.safety_gate_result })
                : '—'}
            </span>
          </dd>
        </div>
      </dl>
      <div className="border-t border-ink-200 pt-2">
        <div className="flex items-center justify-between text-ink-500">
          <span>{t('notebook.summary.progress')}</span>
          <span className="font-mono font-semibold text-ink-800">{progress.percent}%</span>
        </div>
        <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
          <div
            className="h-full rounded-full bg-sentinel-500"
            style={{ width: `${progress.percent}%` }}
          />
        </div>
        <p className="mt-1 text-[11px] text-ink-400">
          {t('notebook.summary.checklistCount', { checked: progress.checked, total: progress.total })}
        </p>
      </div>
      {intelligence?.safety.gate_result === 'BLOCK' && (
        <p className="rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[11px] text-red-800">
          {t('notebook.summary.safetyBlock')}
        </p>
      )}
    </div>
  )
}

function OverviewSection() {
  const { investigation, intelligence } = useSimulationStore()
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')
  if (!investigation) return null
  const overview = investigation.overview

  return (
    <div className="space-y-4">
      <Card title={t('notebook.overview.title')}>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.id')}</dt>
            <dd className="font-mono">{overview.investigation_id}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.village')}</dt>
            <dd>{overview.village_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.scenario')}</dt>
            <dd>{overview.scenario_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.currentWeek')}</dt>
            <dd className="font-mono">
              {overview.week} / {overview.total_weeks}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.signalCategory')}</dt>
            <dd>{overview.primary_signal ?? '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.trend')}</dt>
            <dd>{overview.trend ? t(`trend.${overview.trend}`, { defaultValue: overview.trend }) : '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.evidenceStrength')}</dt>
            <dd>
              <span className={`pill ${evidencePillClass(overview.evidence_strength)}`}>
                {overview.evidence_strength
                  ? t(`evidenceStrength.${overview.evidence_strength}`, {
                      defaultValue: overview.evidence_strength,
                    })
                  : '—'}
              </span>
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.priority')}</dt>
            <dd>
              {overview.investigation_priority
                ? tc(`status.${overview.investigation_priority}`, {
                    defaultValue: overview.investigation_priority,
                  })
                : '—'}
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-ink-500">{t('notebook.overview.safetyResult')}</dt>
            <dd>
              <span className={`pill ${gatePillClass(overview.safety_gate_result)}`}>
                {overview.safety_gate_result
                  ? tc(`status.${overview.safety_gate_result}`, {
                      defaultValue: overview.safety_gate_result,
                    })
                  : '—'}
              </span>
            </dd>
          </div>
        </dl>
        <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
          <p>
            <span className="font-medium text-ink-600">{t('notebook.overview.supporting')}</span>{' '}
            {overview.sources_supporting.join(', ') || t('notebook.overview.none')}
          </p>
          <p>
            <span className="font-medium text-ink-600">{t('notebook.overview.conflicting')}</span>{' '}
            {overview.sources_conflicting.join(', ') || t('notebook.overview.none')}
          </p>
          <p>
            <span className="font-medium text-ink-600">{t('notebook.overview.insufficient')}</span>{' '}
            {overview.sources_insufficient.join(', ') || t('notebook.overview.none')}
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
  const { t } = useTranslation('simulation')

  if (!intelligence) {
    return <Empty>{t('notebook.timeline.empty')}</Empty>
  }

  const viewing = replayWeek !== null ? replayIntelligence : intelligence

  return (
    <div className="space-y-4">
      <Card title={t('notebook.timeline.title')}>
        <SignalTimelineChart timeline={intelligence.timeline} />
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-ink-500">{t('notebook.timeline.inspectWeek')}</span>
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
              {t('notebook.timeline.backToCurrent')}
            </button>
          )}
        </div>
        {replayWeek !== null && (
          <p className="mt-2 text-xs text-amber-800">
            {t('notebook.timeline.viewingHistorical', { week: replayWeek })}
          </p>
        )}
      </Card>

      {viewing && (
        <Card title={t('notebook.timeline.sourceEvolution')}>
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="text-ink-500">
                <th className="py-1 pr-2 font-medium">{t('notebook.timeline.tableSource')}</th>
                <th className="py-1 pr-2 font-medium">{t('notebook.timeline.tableValue')}</th>
                <th className="py-1 font-medium">{t('notebook.timeline.tableReported')}</th>
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
                      <span className="text-ink-400">{t('notebook.timeline.notReported')}</span>
                    ) : (
                      t('notebook.timeline.reported')
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
  const { t } = useTranslation('simulation')
  if (!agentRuns.length) return null

  return (
    <Card title={t('notebook.pipelineCard.title')}>
      <AgentPipelineView agentRuns={agentRuns} pipelineError={pipelineError} />
    </Card>
  )
}

function EvidenceSection() {
  const { intelligence, replayWeek, replayIntelligence } = useSimulationStore()
  const { t } = useTranslation('simulation')
  const viewing = replayWeek !== null ? replayIntelligence : intelligence
  if (!viewing) return <Empty>{t('notebook.evidence.empty')}</Empty>

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
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')
  if (!investigation) return null
  const { contradictions } = investigation

  if (!contradictions.length) {
    return (
      <Card title={t('notebook.contradictions.title')}>
        <Empty>{t('notebook.contradictions.none')}</Empty>
      </Card>
    )
  }

  return (
    <Card title={t('notebook.contradictions.inspectorTitle')}>
      <div className="space-y-3">
        {contradictions.map((entry) => (
          <div key={entry.source} className="rounded-md border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-ink-800">{entry.source}</span>
              <span className="pill bg-amber-100 text-amber-800">
                {tc(`status.${entry.relation}`, { defaultValue: entry.relation })}
              </span>
            </div>
            <p className="mt-1 text-xs text-ink-700">{entry.reason}</p>
            <p className="mt-2 text-[11px] font-medium uppercase tracking-wide text-ink-500">
              {t('notebook.contradictions.suggestedVerification')}
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
  const { t } = useTranslation('simulation')
  if (!investigation) return null
  const entries = investigation.community_context

  return (
    <Card title={t('notebook.context.title')}>
      {entries.length === 0 ? (
        <Empty>{t('notebook.context.empty')}</Empty>
      ) : (
        <ul className="space-y-2">
          {entries.map((entry, index) => (
            <li key={index} className="rounded-md border border-ink-200 bg-ink-50 p-2.5 text-sm">
              <span className="pill bg-ink-100 text-ink-600 text-[10px] font-medium">
                {t('notebook.context.badge')}
              </span>
              <p className="mt-1 text-ink-700">
                {t('notebook.context.weekNote', { week: entry.week, note: entry.note })}
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
  const { t } = useTranslation('simulation')

  if (!investigation) return null

  async function handleAddObservation() {
    setSubmitError(null)
    const week = Number(draftWeek)
    if (!week || !draftSource.trim() || !draftNotes.trim()) {
      setSubmitError(t('notebook.fieldNotes.requiredError'))
      return
    }
    setSubmitting(true)
    try {
      await addInvestigationObservation({ week, source: draftSource.trim(), notes: draftNotes.trim() })
      setDraftWeek('')
      setDraftSource('')
      setDraftNotes('')
    } catch {
      setSubmitError(t('notebook.fieldNotes.saveError'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card title={t('notebook.fieldNotes.notesTitle')}>
        <textarea
          className="input min-h-[140px] w-full"
          placeholder={t('notebook.fieldNotes.placeholder')}
          defaultValue={investigation.notes}
          onChange={(event) => saveInvestigationNotes(event.target.value)}
        />
        <p className="mt-1 text-[11px] text-ink-400">
          {investigationSaving ? t('notebook.fieldNotes.saving') : t('notebook.fieldNotes.savedAuto')}
        </p>
      </Card>

      <Card title={t('notebook.fieldNotes.observationsTitle')}>
        {investigation.observations.length === 0 ? (
          <Empty>{t('notebook.fieldNotes.noObservations')}</Empty>
        ) : (
          <ul className="mb-3 space-y-2">
            {investigation.observations.map((obs) => (
              <li key={obs.id} className="rounded-md border border-ink-200 p-2.5 text-sm">
                <div className="flex items-center justify-between text-xs text-ink-500">
                  <span>{t('notebook.fieldNotes.weekSource', { week: obs.week, source: obs.source })}</span>
                  <span className="pill bg-ink-100 text-ink-600 text-[10px] font-medium">
                    {t('notebook.fieldNotes.badge')}
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
            placeholder={t('notebook.fieldNotes.weekPlaceholder')}
            inputMode="numeric"
            value={draftWeek}
            onChange={(event) => setDraftWeek(event.target.value)}
          />
          <input
            className="input"
            placeholder={t('notebook.fieldNotes.sourcePlaceholder')}
            value={draftSource}
            onChange={(event) => setDraftSource(event.target.value)}
          />
          <input
            className="input"
            placeholder={t('notebook.fieldNotes.notesPlaceholder')}
            value={draftNotes}
            onChange={(event) => setDraftNotes(event.target.value)}
          />
          <button
            type="button"
            className="btn-sentinel py-1.5 text-xs"
            disabled={submitting}
            onClick={() => void handleAddObservation()}
          >
            {t('notebook.fieldNotes.add')}
          </button>
        </div>
        {submitError && <p className="mt-2 text-xs text-red-700">{submitError}</p>}
      </Card>
    </div>
  )
}

function ChecklistSection() {
  const { investigation, investigationSaving, updateInvestigationChecklist } = useSimulationStore()
  const { t } = useTranslation('simulation')
  if (!investigation) return null
  const { items, values, progress } = investigation.checklist

  return (
    <Card title={t('notebook.checklist.title')}>
      <p className="text-xs text-ink-500">
        {t('notebook.checklist.progressLine', {
          checked: progress.checked,
          total: progress.total,
          percent: progress.percent,
        })}
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
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')
  if (!whatIfResult) {
    return (
      <Card title={t('notebook.decision.whatIfTitle')}>
        <Empty>{t('notebook.decision.whatIfEmpty')}</Empty>
      </Card>
    )
  }

  const evidenceLabel = (value: string | null) =>
    value ? t(`evidenceStrength.${value}`, { defaultValue: value }) : '—'
  const gateLabel = (value: string | null) =>
    value ? tc(`status.${value}`, { defaultValue: value }) : '—'

  return (
    <Card title={t('notebook.decision.whatIfTitle')}>
      <p className="pill bg-ink-100 text-ink-600 font-semibold">{t('whatIf.hypotheticalBadge')}</p>
      <dl className="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="text-ink-500">{t('notebook.decision.evidenceStrength')}</dt>
          <dd className="mt-0.5">
            {t('notebook.decision.original', { value: evidenceLabel(whatIfResult.original.evidence_strength) })}
            <br />
            {t('notebook.decision.whatIfValue', {
              value: evidenceLabel(whatIfResult.hypothetical.safety.evidence_strength),
            })}
          </dd>
        </div>
        <div>
          <dt className="text-ink-500">{t('notebook.decision.safety')}</dt>
          <dd className="mt-0.5">
            {t('notebook.decision.original', { value: gateLabel(whatIfResult.original.gate_result) })}
            <br />
            {t('notebook.decision.whatIfValue', {
              value: gateLabel(whatIfResult.hypothetical.safety.gate_result),
            })}
          </dd>
        </div>
        <div>
          <dt className="text-ink-500">{t('notebook.decision.changedSources')}</dt>
          <dd className="mt-0.5">{whatIfResult.changed_sources.join(', ') || t('notebook.decision.none')}</dd>
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
  const { t } = useTranslation('simulation')
  const { t: tc } = useTranslation('common')

  if (!investigation || !intelligence) return null

  const blocked = intelligence.safety.gate_result === 'BLOCK'
  const suggested = investigation.suggested_decision

  async function handleDecide(decision: InvestigationDecisionValue) {
    setDecisionError(null)
    try {
      await recordInvestigationDecision(decision, reason)
    } catch {
      setDecisionError(t('notebook.decision.recordError'))
    }
  }

  /** `t('decision.<KEY>')` mirrors `INVESTIGATION_DECISION_LABELS` exactly
   *  (same seven backend enum keys, same English default) — the backend
   *  `InvestigationDecisionValue` itself is never touched, only which
   *  string is displayed for it. */
  const decisionLabel = (value: InvestigationDecisionValue) =>
    t(`decision.${value}`, { defaultValue: INVESTIGATION_DECISION_LABELS[value] })

  return (
    <div className="space-y-4">
      <Card title={t('notebook.decision.evidenceSummaryTitle')}>
        <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-ink-500">{t('notebook.decision.evidence')}</dt>
            <dd className="font-medium">
              {t(`evidenceStrength.${intelligence.explanation.evidence_strength}`, {
                defaultValue: intelligence.explanation.evidence_strength,
              })}
            </dd>
          </div>
          <div>
            <dt className="text-ink-500">{t('notebook.decision.safety')}</dt>
            <dd className="font-medium">
              {intelligence.safety.gate_result
                ? tc(`status.${intelligence.safety.gate_result}`, {
                    defaultValue: intelligence.safety.gate_result,
                  })
                : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-ink-500">{t('notebook.decision.dataQuality')}</dt>
            <dd className="font-medium">{intelligence.data_quality.completeness_pct}%</dd>
          </div>
          <div>
            <dt className="text-ink-500">{t('notebook.decision.checklist')}</dt>
            <dd className="font-medium">{investigation.checklist.progress.percent}%</dd>
          </div>
        </dl>
      </Card>

      <WhatIfComparisonCard />

      <Card title={t('notebook.decision.workspaceTitle')}>
        <p className="pill bg-ink-100 text-ink-600 font-semibold">
          {t('notebook.decision.systemIntelligenceBadge')}
        </p>
        <p className="mt-2 text-sm text-ink-700">{intelligence.explanation.routed_reason}</p>

        {blocked ? (
          <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <p className="font-semibold">{t('notebook.decision.safetyBlockTitle')}</p>
            <p className="mt-1">{t('notebook.decision.safetyBlockMessage')}</p>
          </div>
        ) : (
          <>
            {suggested && (
              <p className="mt-3 rounded-md border border-sentinel-200 bg-sentinel-50 px-3 py-2 text-xs text-sentinel-800">
                {t('notebook.decision.systemSuggested')} <strong>{decisionLabel(suggested)}</strong>{' '}
                {t('notebook.decision.suggestionOnly')}
              </p>
            )}

            <p className="mt-4 pill bg-ink-800 text-white font-semibold">
              {t('notebook.decision.officerDecisionBadge')}
            </p>
            <textarea
              className="input mt-2 w-full"
              rows={2}
              placeholder={t('notebook.decision.reasonPlaceholder')}
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
                    {decisionLabel(decision)}
                  </button>
                ),
              )}
            </div>
            {decisionError && <p className="mt-2 text-xs text-red-700">{decisionError}</p>}
          </>
        )}

        {investigation.decision.value && (
          <p className="mt-4 rounded-md border border-care-200 bg-care-50 px-3 py-2 text-xs text-care-800">
            {t('notebook.decision.recorded')}{' '}
            <strong>
              {t(`decision.${investigation.decision.value}`, {
                defaultValue: investigation.decision.value_display,
              })}
            </strong>{' '}
            {t('notebook.decision.recordedBy', { by: investigation.decision.decided_by ?? '—' })}
            {investigation.decision.decided_at &&
              ` ${t('notebook.decision.recordedOn', {
                date: new Date(investigation.decision.decided_at).toLocaleString(),
              })}`}
            .
          </p>
        )}
      </Card>
    </div>
  )
}

function RecommendationSection() {
  const { intelligence, investigation } = useSimulationStore()
  const { t } = useTranslation('simulation')
  if (!intelligence || !investigation) return null

  return (
    <Card title={t('notebook.recommendation.title')}>
      <p className="text-sm text-ink-700">{intelligence.explanation.suggested_verification}</p>
      {investigation.decision.value ? (
        <p className="mt-3 text-sm text-ink-800">
          <span className="font-medium">{t('notebook.recommendation.officerDecision')}</span>{' '}
          {t(`decision.${investigation.decision.value}`, {
            defaultValue: investigation.decision.value_display,
          })}
          {investigation.decision.reason && ` — ${investigation.decision.reason}`}
        </p>
      ) : (
        <p className="mt-3 text-xs text-ink-400">{t('notebook.recommendation.noDecision')}</p>
      )}
      <p className="mt-3 text-[11px] text-ink-400">{t('notebook.recommendation.footer')}</p>
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
  const { t } = useTranslation('simulation')

  useEffect(() => {
    setComment(feedback?.comment ?? '')
  }, [feedback?.comment])

  if (feedbackLoading && !feedback) return <Loading label={t('notebook.feedback.loading')} />

  async function handleFeedbackChange(patch: Parameters<typeof saveFeedback>[0]) {
    setJustSaved(false)
    try {
      await saveFeedback(patch)
      setJustSaved(true)
    } catch {
      // feedbackError is already surfaced below by the store.
    }
  }

  /** `t('feedbackLabels.<group>.<KEY>')` mirrors each `FEEDBACK_*_LABELS`
   *  constant exactly (same backend enum keys, English default via
   *  `defaultValue`) — only the displayed word changes, never the value
   *  sent to `saveFeedback`. */
  const usefulnessLabels = (
    Object.fromEntries(
      (Object.keys(FEEDBACK_USEFULNESS_LABELS) as FeedbackUsefulness[]).map((key) => [
        key,
        t(`feedbackLabels.usefulness.${key}`, { defaultValue: FEEDBACK_USEFULNESS_LABELS[key] }),
      ]),
    ) as Record<FeedbackUsefulness, string>
  )
  const evidenceSufficiencyLabels = (
    Object.fromEntries(
      (Object.keys(FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS) as FeedbackEvidenceSufficiency[]).map((key) => [
        key,
        t(`feedbackLabels.evidenceSufficiency.${key}`, {
          defaultValue: FEEDBACK_EVIDENCE_SUFFICIENCY_LABELS[key],
        }),
      ]),
    ) as Record<FeedbackEvidenceSufficiency, string>
  )
  const yesPartiallyNoLabels = (
    Object.fromEntries(
      (Object.keys(FEEDBACK_YES_PARTIALLY_NO_LABELS) as FeedbackYesPartiallyNo[]).map((key) => [
        key,
        t(`feedbackLabels.yesPartiallyNo.${key}`, { defaultValue: FEEDBACK_YES_PARTIALLY_NO_LABELS[key] }),
      ]),
    ) as Record<FeedbackYesPartiallyNo, string>
  )
  const yesNoLabels = (
    Object.fromEntries(
      (Object.keys(FEEDBACK_YES_NO_LABELS) as FeedbackYesNo[]).map((key) => [
        key,
        t(`feedbackLabels.yesNo.${key}`, { defaultValue: FEEDBACK_YES_NO_LABELS[key] }),
      ]),
    ) as Record<FeedbackYesNo, string>
  )

  return (
    <Card title={t('notebook.feedback.title')}>
      <p className="pill bg-ink-100 text-ink-600 font-semibold">{t('notebook.feedback.badge')}</p>
      <p className="mt-2 text-xs text-ink-500">{t('notebook.feedback.description')}</p>

      <FeedbackChoiceGroup
        label={t('notebook.feedback.usefulnessQuestion')}
        options={['VERY_USEFUL', 'USEFUL', 'PARTIALLY_USEFUL', 'NOT_USEFUL'] as const}
        labels={usefulnessLabels}
        value={feedback?.usefulness ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackUsefulness) => void handleFeedbackChange({ usefulness: value })}
      />
      <FeedbackChoiceGroup
        label={t('notebook.feedback.evidenceSufficiencyQuestion')}
        options={['SUFFICIENT', 'PARTIALLY_SUFFICIENT', 'INSUFFICIENT'] as const}
        labels={evidenceSufficiencyLabels}
        value={feedback?.evidence_sufficiency ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackEvidenceSufficiency) =>
          void handleFeedbackChange({ evidence_sufficiency: value })
        }
      />
      <FeedbackChoiceGroup
        label={t('notebook.feedback.recommendationHelpfulQuestion')}
        options={['YES', 'PARTIALLY', 'NO'] as const}
        labels={yesPartiallyNoLabels}
        value={feedback?.recommendation_helpful ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackYesPartiallyNo) =>
          void handleFeedbackChange({ recommendation_helpful: value })
        }
      />
      <FeedbackChoiceGroup
        label={t('notebook.feedback.additionalVerificationQuestion')}
        options={['YES', 'NO'] as const}
        labels={yesNoLabels}
        value={feedback?.additional_verification_required ?? ''}
        disabled={feedbackSaving}
        onSelect={(value: FeedbackYesNo) =>
          void handleFeedbackChange({ additional_verification_required: value })
        }
      />

      <div className="mt-4 border-t border-ink-200 pt-3">
        <p className="text-xs font-medium text-ink-600">{t('notebook.feedback.commentLabel')}</p>
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
            {t('notebook.feedback.save')}
          </button>
          {justSaved && !feedbackSaving && (
            <span className="text-xs text-care-700">{t('notebook.feedback.saved')}</span>
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
  const { t } = useTranslation('simulation')

  useEffect(() => {
    if (lastSeenWeek.current === null) lastSeenWeek.current = liveWeek
  }, [liveWeek])

  if (liveStatus === 'IDLE' || liveWeek === null) return null
  if (lastSeenWeek.current !== null && liveWeek <= lastSeenWeek.current) return null
  if (dismissedWeek === liveWeek) return null

  return (
    <div className="card mb-3 flex items-center justify-between gap-3 border border-sentinel-200 bg-sentinel-50 px-4 py-2.5 text-sm text-sentinel-800">
      <span>{t('notebook.liveUpdate.banner', { week: liveWeek })}</span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="btn-ghost py-1 text-xs"
          onClick={() => {
            if (sessionId) void loadInvestigation(sessionId)
            lastSeenWeek.current = liveWeek
          }}
        >
          {t('notebook.liveUpdate.refresh')}
        </button>
        <button
          type="button"
          className="text-xs text-sentinel-600 underline"
          onClick={() => setDismissedWeek(liveWeek)}
        >
          {t('notebook.liveUpdate.dismiss')}
        </button>
      </div>
    </div>
  )
}

export default function InvestigationNotebookPage() {
  const { sessionId: sessionIdParam } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const sessionId = Number(sessionIdParam)
  const { t } = useTranslation('simulation')

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
    return <ErrorNote message={t('notebook.errors.invalidLink')} />
  }

  if (investigationLoading && !investigation) {
    return <Loading label={t('notebook.errors.loading')} />
  }

  if (investigationError && !investigation) {
    return <ErrorNote message={investigationError} onRetry={() => void loadInvestigation(sessionId)} />
  }

  if (!investigation) {
    return <Empty>{t('notebook.errors.openFromLab')}</Empty>
  }

  const currentIndex = SECTIONS.findIndex((section) => section.key === investigationSection)
  const SectionComponent = SECTION_CONTENT[investigationSection as SectionKey] ?? OverviewSection

  return (
    <div className="flex flex-col gap-3">
      <div className="card flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-ink-800">{t('notebook.header.title')}</p>
          <p className="text-xs text-ink-500">
            {investigation.overview.village_name} ·{' '}
            {t('notebook.header.weekLabel', { week: investigation.overview.week })}
          </p>
        </div>
        <SyntheticBadge />
      </div>

      <LiveUpdateBanner />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(200px,20%)_1fr_minmax(220px,23%)]">
        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label={t('notebook.aria.nav')}
        >
          <SectionNav />
        </aside>

        <main
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label={t('notebook.aria.content')}
        >
          <SectionComponent />
        </main>

        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label={t('notebook.aria.summary')}
        >
          <InvestigationSummaryPanel />
        </aside>
      </div>

      <div
        className="card sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 px-4 py-3"
        role="toolbar"
        aria-label={t('notebook.aria.footer')}
      >
        <button
          type="button"
          className="btn-ghost py-1.5"
          onClick={() => navigate(activeSession ? '/officer/simulation' : '/officer/simulation')}
        >
          {t('notebook.footer.back')}
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-ghost py-1.5"
            disabled={currentIndex <= 0}
            onClick={() => setInvestigationSection(SECTIONS[Math.max(0, currentIndex - 1)].key)}
          >
            {t('notebook.footer.previous')}
          </button>
          <button
            type="button"
            className="btn-ghost py-1.5"
            disabled={currentIndex >= SECTIONS.length - 1}
            onClick={() =>
              setInvestigationSection(SECTIONS[Math.min(SECTIONS.length - 1, currentIndex + 1)].key)
            }
          >
            {t('notebook.footer.next')}
          </button>
        </div>
        <button
          type="button"
          className="btn-sentinel py-1.5"
          disabled={investigationReportLoading}
          onClick={() => void exportInvestigationReport()}
        >
          {investigationReportLoading ? t('notebook.footer.generating') : t('notebook.footer.exportReport')}
        </button>
      </div>

      <p className="text-xs text-ink-400">{t('notebook.footer.disclaimer')}</p>
    </div>
  )
}
