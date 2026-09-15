import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { Empty, ErrorNote, Loading, SyntheticBadge } from '@/components/ui'
import { useAsync } from '@/hooks/useAsync'
import { api } from '@/services/api'
import { useSimulationStore } from '@/store/simulation'
import { useAuth } from '@/store/auth'
import {
  SIMULATION_STAGE_ORDER,
  type InvestigationDecisionValue,
  type SimulationAgentName,
  type SimulationAgentRun,
  type SimulationConstellationEntry,
  type SimulationDataQuality,
  type SimulationExplanation,
  type SimulationIntelligence,
  type SimulationSafetyGateResult,
  type SimulationSafetyResult,
  type SimulationScenario,
  type SimulationSourceFusionEntry,
  type SimulationSourceValue,
  type SimulationTimelinePoint,
  type SimulationWhatIfResult,
} from '@/types'

/**
 * Reads the authenticated officer's own village from the existing auth
 * store (`useAuth().user`, populated at login/`/auth/me/` exactly like the
 * rest of the app) — never a second village state, never a value the user
 * can change. There is deliberately no dropdown, no selector, and no
 * frontend-supplied village id anywhere on this page: the backend resolves
 * and enforces the officer's village independently (see
 * `simulation.permissions`/`simulation.services.SimulationEngine`), this
 * banner is a read-only reflection of that same server-side fact.
 */
function CurrentScopeBanner() {
  const user = useAuth((state) => state.user)

  return (
    <div className="rounded-lg border border-sentinel-200 bg-sentinel-50 px-4 py-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-sentinel-700">
        Current operational scope
      </div>
      <p className="text-lg font-semibold text-sentinel-900 mt-0.5">
        {user?.village_name ?? 'No village assigned'}
      </p>
      <p className="text-xs text-sentinel-800 mt-1">
        Fixed to your own assigned area. There is no option to switch village here.
      </p>
    </div>
  )
}

/**
 * Compact scenario picker, header row (replaces the four large scenario
 * cards that used to occupy the whole pre-session screen). Reuses the
 * EXACT existing `selectScenario`/`startSession` store actions a card's
 * "Start Simulation" button already called — this is only a new UI entry
 * point onto that same logic, never a second session-creation mechanism.
 *
 * Choosing a scenario while a DIFFERENT session is already active first
 * calls the existing `resetSession()` (the same reset an officer would
 * otherwise reach via "Reset Simulation") before starting the new one —
 * this is the one genuinely new state transition this selector introduces
 * (switching scenarios without first manually resetting was not possible
 * through the old card UI, since cards only ever rendered when no session
 * was active), so it is the one place stale state must be explicitly
 * guarded against: without this, agentRuns/timeline/replay position/
 * What-If result/live connection/investigation state from the OLD session
 * would otherwise leak into the new one's view.
 */
function ScenarioSelector() {
  const { availableScenarios, selectedScenario, activeSession, selectScenario, startSession, resetSession } =
    useSimulationStore()
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)

  if (availableScenarios.length === 0) return null

  const currentId = activeSession ? activeSession.scenario_id : selectedScenario?.id ?? ''

  async function handleChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const nextId = Number(event.target.value)
    const next = availableScenarios.find((scenario) => scenario.id === nextId)
    if (!next || next.id === currentId) return

    setStartError(null)
    setStarting(true)
    try {
      if (activeSession) resetSession()
      selectScenario(next)
      await startSession(next.id)
    } catch (err) {
      setStartError(err instanceof Error ? err.message : 'Could not start the simulation.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <label htmlFor="scenario-selector" className="text-xs font-medium text-ink-600">
        Scenario
      </label>
      <select
        id="scenario-selector"
        className="input w-auto py-1.5 text-sm"
        value={currentId}
        disabled={starting}
        onChange={(event) => void handleChange(event)}
      >
        {!currentId && (
          <option value="" disabled>
            Select a scenario…
          </option>
        )}
        {availableScenarios.map((scenario) => (
          <option key={scenario.id} value={scenario.id}>
            {scenario.name}
          </option>
        ))}
      </select>
      {starting && <span className="text-xs text-ink-500">Starting…</span>}
      {startError && <span className="text-xs text-red-700">{startError}</span>}
    </div>
  )
}

const STAGE_LABELS: Record<SimulationAgentName, string> = {
  ingestion: 'Data Ingestion',
  signal_analysis: 'Signal Analysis',
  correlation: 'Correlation',
  evidence: 'Evidence',
  safety: 'Safety',
}

/**
 * Phase 4 legend. Every stage is deterministic rule-based logic — the same
 * input always produces the same output. Signal Analysis is the one
 * exception, and only partially: its TREND classification is exactly as
 * deterministic as every other stage, but the one-sentence explanation
 * attached to it may optionally be phrased by an LLM. That LLM call can
 * fail, time out, or (if ever prompted badly) disagree with the trend —
 * none of that is allowed to change the trend value itself, which is
 * computed first and never overwritten (see `simulation/orchestrator.py`).
 */
function PipelineLegend() {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-ink-500">
      <span className="inline-flex items-center gap-1.5">
        <span className="pill bg-sentinel-100 text-sentinel-700">
          Deterministic
        </span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="pill bg-violet-100 text-violet-700">
          LLM-assisted wording
        </span>
      </span>
    </div>
  )
}

function trendPillClass(trend: string): string {
  switch (trend) {
    case 'SIGNAL_DETECTED':
      return 'bg-red-100 text-red-700'
    case 'INCREASING':
      return 'bg-amber-100 text-amber-700'
    case 'NORMAL':
      return 'bg-care-100 text-care-700'
    default:
      return 'bg-ink-100 text-ink-700'
  }
}

function relationshipPillClass(relationship: string): string {
  switch (relationship) {
    case 'SUPPORTING':
      return 'bg-care-100 text-care-700'
    case 'CONFLICTING':
      return 'bg-red-100 text-red-700'
    default:
      return 'bg-ink-100 text-ink-600'
  }
}

/** PASS/BLOCK/INSUFFICIENT — the Phase 6 Safety Engine's own gate
 *  vocabulary. Reused for both the pipeline card's compact summary and
 *  the full `SafetyGatePanel` banner below, so the two never show
 *  different colours for the same result. */
function gateResultPillClass(gateResult: string): string {
  switch (gateResult) {
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

/** Stage-specific rendering of `output` — each stage has its own JSON
 *  shape (Phase 4 task §4/§7/§8/§9), so this reads known fields per stage
 *  defensively rather than assuming one shared shape. */
function StageDetails({
  name,
  output,
}: {
  name: SimulationAgentName
  output: Record<string, unknown>
}) {
  if (name === 'ingestion') {
    const sources = (output.sources ?? {}) as Record<
      string,
      { reported: boolean; value: number | null }
    >
    return (
      <ul className="mt-2 space-y-1 text-xs">
        {Object.entries(sources).map(([source, info]) => (
          <li key={source} className="flex items-center justify-between">
            <span className="text-ink-600">{source}</span>
            <span className="font-mono tabular-nums text-ink-800">
              {info.reported ? (
                info.value
              ) : (
                <span className="italic text-ink-400">not submitted</span>
              )}
            </span>
          </li>
        ))}
      </ul>
    )
  }

  if (name === 'signal_analysis') {
    const trend = String(output.trend ?? '')
    const current = output.current_value as number | undefined
    const previous = output.previous_value as number | null | undefined
    const usedLlm = Boolean(output.explanation_used_llm)
    return (
      <div className="mt-2 space-y-1.5 text-xs">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="pill bg-ink-100 text-ink-700">
            {String(output.primary_signal ?? '')}
          </span>
          <span className={`pill ${trendPillClass(trend)}`}>{trend}</span>
          <span className="text-ink-500">
            {previous == null ? 'no prior week to compare' : `${previous} → ${current}`}
          </span>
          {usedLlm && (
            <span className="pill bg-violet-100 text-violet-700">
              LLM-assisted wording
            </span>
          )}
        </div>
      </div>
    )
  }

  if (name === 'correlation') {
    const relationships = (output.relationships ?? []) as {
      source: string
      relationship: string
      reason: string
    }[]
    return (
      <ul className="mt-2 space-y-1 text-xs">
        {relationships.map((r) => (
          <li key={r.source} className="flex items-center gap-2">
            <span className={`pill ${relationshipPillClass(r.relationship)}`}>
              {r.relationship}
            </span>
            <span className="text-ink-600">{r.source}</span>
          </li>
        ))}
      </ul>
    )
  }

  if (name === 'evidence') {
    const summary = (output.reporting_summary ?? {}) as {
      reported_sources?: number
      missing_sources?: number
    }
    return (
      <p className="mt-2 text-xs text-ink-600">
        {summary.reported_sources ?? 0} source(s) reported,{' '}
        {summary.missing_sources ?? 0} missing this week.
      </p>
    )
  }

  if (name === 'safety') {
    const gateResult = String(output.gate_result ?? '')
    const checks = Array.isArray(output.checks) ? (output.checks as unknown[]).length : 0
    return (
      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
        <span className={`pill ${gateResultPillClass(gateResult)}`}>{gateResult}</span>
        <span className="text-ink-500">
          {checks} checks · human review required
        </span>
      </div>
    )
  }

  return null
}

/**
 * One pipeline stage, rendered purely from the `SimulationAgentRun` the
 * backend returned — `run` is `undefined` before the officer has advanced
 * the session past week 1 (the pipeline has genuinely not run yet), which
 * is shown as a plain neutral placeholder rather than any kind of fake
 * "in progress" animation.
 */
function AgentStageCard({
  name,
  run,
}: {
  name: SimulationAgentName
  run: SimulationAgentRun | undefined
}) {
  const label = STAGE_LABELS[name]

  if (!run) {
    return (
      <div className="rounded-lg border border-dashed border-ink-200 bg-ink-50 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-ink-600">{label}</span>
          <span className="pill bg-ink-100 text-ink-400">Not yet run</span>
        </div>
        <p className="mt-1 text-xs text-ink-400">
          Runs the next time this session advances a week.
        </p>
      </div>
    )
  }

  const failed = run.status === 'FAILED'
  const waiting = run.status === 'WAITING'

  const statusPillClass = failed
    ? 'bg-red-100 text-red-700'
    : waiting
      ? 'bg-ink-100 text-ink-600'
      : 'bg-care-100 text-care-700'

  const explanation =
    typeof run.output.explanation === 'string' ? run.output.explanation : null
  const errorText =
    failed && typeof run.output.error === 'string' ? run.output.error : null

  return (
    <div
      className={`rounded-lg border p-3 ${
        failed ? 'border-red-200 bg-red-50' : 'border-ink-200 bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-1.5">
        <span className="text-sm font-medium text-ink-800">{label}</span>
        <div className="flex items-center gap-1.5">
          <span className={`pill ${statusPillClass}`}>
            {run.status_display}
          </span>
          {run.duration_ms != null && (
            <span className="text-[11px] text-ink-400">
              {run.duration_ms} ms
            </span>
          )}
        </div>
      </div>

      {errorText ? (
        <p className="mt-1.5 text-xs text-red-700">{errorText}</p>
      ) : explanation ? (
        <p className="mt-1.5 text-xs text-ink-600">{explanation}</p>
      ) : null}

      {!failed && <StageDetails name={name} output={run.output} />}
    </div>
  )
}

/**
 * The 5-stage pipeline, in its permanent fixed order. Every status shown
 * here is a `SimulationAgentRun` the backend already persisted — there is
 * no client-side timer or animation standing in for "processing" (Phase 4
 * task §16/§29): the request is synchronous, so by the time this renders,
 * each stage has already reached its final status.
 */
export function AgentPipelineView({
  agentRuns,
  pipelineError,
}: {
  agentRuns: SimulationAgentRun[]
  pipelineError: string | null
}) {
  return (
    <div className="mt-4 border-t border-ink-200 pt-3">
      <div className="label">Multi-agent pipeline</div>
      <div className="mt-2">
        <PipelineLegend />
      </div>

      {pipelineError && (
        <div className="mt-2">
          <ErrorNote message={pipelineError} />
        </div>
      )}

      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {SIMULATION_STAGE_ORDER.map((name) => (
          <AgentStageCard
            key={name}
            name={name}
            run={agentRuns.find((run) => run.agent_name === name)}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * Phase 5 — Signal Timeline. Plots exactly `intelligence.timeline`'s own
 * `value` per week — never a normalized percentage/index/score (task §4).
 * `value: null` (a genuinely absent week) is left out of the line rather
 * than passed through `connectNulls`, so it renders as a visible gap, not
 * a bridged/interpolated segment (task §5) — the one deliberate departure
 * from the `stroke`/margin conventions in `pages/officer/Dashboard.tsx`,
 * which this otherwise matches exactly for visual consistency. A plain
 * text list beneath the chart repeats every week's value and status as
 * words, so the same information never depends on chart colour alone
 * (task §31).
 */
export function SignalTimelineChart({ timeline }: { timeline: SimulationTimelinePoint[] }) {
  if (timeline.length === 0) {
    return <Empty>No reporting weeks are available yet for this session.</Empty>
  }

  const primarySignal = timeline.find((point) => point.primary_signal)?.primary_signal ?? null
  const chartData = timeline.map((point) => ({ week: point.week, value: point.value }))

  return (
    <div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 8, right: 12, bottom: 14, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f4" />
            <XAxis
              dataKey="week"
              tick={{ fontSize: 11, fill: '#8a94a6' }}
              tickLine={false}
              axisLine={{ stroke: '#dde1e9' }}
              label={{
                value: 'Reporting Week',
                position: 'insideBottom',
                offset: -8,
                fontSize: 11,
                fill: '#8a94a6',
              }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: '#8a94a6' }}
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              label={{
                value: 'Reported Cases',
                angle: -90,
                position: 'insideLeft',
                fontSize: 11,
                fill: '#8a94a6',
              }}
            />
            <Tooltip
              formatter={(value: number | string) => [
                value === null || value === undefined ? 'Not reported' : `${value} reported`,
                primarySignal ?? 'Signal',
              ]}
              contentStyle={{ fontSize: 12, borderRadius: 6, border: '1px solid #dde1e9' }}
            />
            <Line type="monotone" dataKey="value" stroke="#3b5bad" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-3 space-y-1">
        {timeline.map((point) => (
          <li
            key={point.week}
            className="flex flex-wrap items-center justify-between gap-2 text-sm"
          >
            <span className="text-ink-600">Week {point.week}</span>
            <span className="font-mono tabular-nums text-ink-800">
              {point.value === null ? (
                <span className="italic text-ink-400">not reported</span>
              ) : (
                point.value
              )}
            </span>
            <span className="pill bg-ink-100 text-ink-700">{point.status}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Phase 5 — Evidence Constellation. Purely a rendering of
 * `intelligence.constellation`, itself a direct read of Phase 4's own
 * persisted `correlation` agent-run output (see `simulation/intelligence.py`)
 * — no relationship is computed here. `relationshipPillClass` is the same
 * function `AgentStageCard` already uses for the identical concept, reused
 * rather than redefined.
 */
export function EvidenceConstellation({
  constellation,
  primarySignal,
}: {
  constellation: SimulationConstellationEntry[]
  primarySignal: string | null
}) {
  if (constellation.length === 0) {
    return (
      <Empty>
        Evidence relationships appear once this session has advanced past week 1.
      </Empty>
    )
  }

  return (
    <div className="flex flex-col items-center">
      <span className="pill bg-sentinel-100 px-4 py-1.5 text-sm text-sentinel-700">
        PRIMARY SIGNAL — {primarySignal ?? 'Unknown'}
      </span>
      <span className="my-2 h-6 w-px bg-ink-200" aria-hidden="true" />
      <div className="flex flex-wrap justify-center gap-3">
        {constellation.map((entry) => (
          <div key={entry.source} className="flex flex-col items-center">
            <span className="h-4 w-px bg-ink-200" aria-hidden="true" />
            <div className="mt-1 min-w-[130px] rounded-lg border border-ink-200 bg-white px-3 py-2 text-center">
              <div className="text-sm font-semibold text-ink-800">{entry.source}</div>
              <span className={`pill mt-1 ${relationshipPillClass(entry.relation)}`}>
                {entry.relation}
              </span>
              <p className="mt-1 text-xs text-ink-500">{entry.reason}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Phase 5 — Source Fusion. A compact table view of the same
 * `correlation` relationships the constellation above renders as a
 * diagram — one shared computation, two presentations (task §19/§20).
 * Every row is explicitly labelled "Synthetic simulation source" so a
 * source name like "Pharmacy" is never mistaken for a live integration
 * (task §9/§50).
 */
export function SourceFusionPanel({ sourceFusion }: { sourceFusion: SimulationSourceFusionEntry[] }) {
  if (sourceFusion.length === 0) {
    return (
      <Empty>Source comparison appears once this session has advanced past week 1.</Empty>
    )
  }

  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="w-full min-w-[520px]">
        <thead>
          <tr>
            <th className="table-head">Source</th>
            <th className="table-head">Status</th>
            <th className="table-head">This week</th>
            <th className="table-head">Reason</th>
          </tr>
        </thead>
        <tbody>
          {sourceFusion.map((row) => (
            <tr key={row.source} className="hover:bg-ink-50">
              <td className="table-cell font-medium text-ink-800">
                {row.source}
                <div className="text-[11px] font-normal text-ink-400">
                  Synthetic simulation source
                </div>
              </td>
              <td className="table-cell">
                <span className={`pill ${relationshipPillClass(row.relation)}`}>
                  {row.relation}
                </span>
              </td>
              <td className="table-cell font-mono tabular-nums">
                {row.reported === false ? (
                  <span className="italic text-ink-400">not submitted</span>
                ) : (
                  row.current_value
                )}
              </td>
              <td className="table-cell text-ink-600">{row.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Phase 5 — Data Quality Lens. `completeness_pct` (overall and per source)
 * is exactly `data_quality.completeness_pct`/`.sources[].completeness_pct`
 * from the backend — `reported_weeks / expected_weeks`, computed once in
 * `simulation/intelligence.py` and never recalculated here (task §10/§19).
 * Missing periods are listed by name, never folded into a single number
 * that would let a reader miss which source/week is actually affected.
 */
export function DataQualityLens({ dataQuality }: { dataQuality: SimulationDataQuality }) {
  return (
    <div>
      <div className="grid gap-4 sm:grid-cols-3">
        <div>
          <div className="label">Reporting completeness</div>
          <p className="text-lg font-semibold text-ink-800">
            {dataQuality.completeness_pct}%
          </p>
        </div>
        <div>
          <div className="label">Historical window</div>
          <p className="text-sm font-medium text-ink-800">{dataQuality.window_label}</p>
        </div>
        <div>
          <div className="label">Duplicate reports checked</div>
          <p className="text-sm font-medium text-ink-800">
            {dataQuality.duplicates_checked ? 'Yes' : 'Not tracked in this simulation'}
          </p>
        </div>
      </div>

      <div className="mt-4 border-t border-ink-200 pt-3">
        <div className="label">Per-source completeness</div>
        <ul className="mt-1 space-y-1">
          {dataQuality.sources.map((source) => (
            <li key={source.source} className="flex items-center justify-between text-sm">
              <span className="text-ink-600">{source.source}</span>
              <span className="font-mono tabular-nums text-ink-800">
                {source.reported_weeks}/{source.expected_weeks} weeks ({source.completeness_pct}%)
              </span>
            </li>
          ))}
        </ul>
      </div>

      {dataQuality.missing.length > 0 && (
        <div className="mt-4 border-t border-ink-200 pt-3">
          <div className="label">Missing reporting</div>
          <ul className="mt-1 space-y-0.5 text-sm text-ink-600">
            {dataQuality.missing.map((entry) => (
              <li key={entry}>— {entry}</li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-ink-400">
            A missing report is never treated as a reported zero.
          </p>
        </div>
      )}
    </div>
  )
}

function evidenceStrengthPillClass(strength: string): string {
  switch (strength) {
    case 'STRONG':
      return 'bg-sentinel-100 text-sentinel-700'
    case 'MODERATE':
      return 'bg-amber-100 text-amber-800'
    default:
      return 'bg-ink-100 text-ink-600'
  }
}

/**
 * Phase 5 — "Why am I seeing this?" No modal/drawer component exists
 * elsewhere in this codebase to reuse, so this is a small, dependency-free
 * overlay in the project's own plain-Tailwind style — closeable by its own
 * button, a click on the backdrop, or Escape (task §14/§31).
 *
 * Every field is read directly off `explanation` — nothing here is
 * generated or rephrased client-side, and `safety_status` is always the
 * literal truthful backend string (never "passed"/"failed"/"approved":
 * the real Safety Engine is Phase 6, see `simulation/orchestrator.py`'s
 * `_safety_stub`).
 */
export function WhyAmISeeingThisPanel({ explanation }: { explanation: SimulationExplanation }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <>
      <button type="button" className="btn-ghost" onClick={() => setOpen(true)}>
        Why am I seeing this?
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink-900/40 px-4"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="why-am-i-seeing-this-heading"
            className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2
                id="why-am-i-seeing-this-heading"
                className="text-base font-semibold text-ink-900"
              >
                Why am I seeing this?
              </h2>
              <button
                type="button"
                className="btn-ghost py-1"
                onClick={() => setOpen(false)}
                aria-label="Close"
              >
                Close
              </button>
            </div>

            <dl className="mt-4 space-y-3 text-sm">
              <div>
                <dt className="label">Signal</dt>
                <dd className="text-ink-800">{explanation.signal}</dd>
              </div>
              <div>
                <dt className="label">Supporting sources</dt>
                <dd className="text-ink-800">
                  {explanation.sources_supporting.join(', ') || 'None'}
                </dd>
              </div>
              <div>
                <dt className="label">Conflicting sources</dt>
                <dd className="text-ink-800">
                  {explanation.sources_conflicting.join(', ') || 'None'}
                </dd>
              </div>
              <div>
                <dt className="label">Insufficient / missing sources</dt>
                <dd className="text-ink-800">
                  {explanation.sources_insufficient.join(', ') || 'None'}
                </dd>
              </div>
              <div>
                <dt className="label">Reporting periods</dt>
                <dd className="text-ink-800">{explanation.reporting_periods}</dd>
              </div>
              <div>
                <dt className="label">Data quality</dt>
                <dd className="text-ink-800">{explanation.data_quality_summary}</dd>
              </div>
              <div>
                <dt className="label">Preliminary evidence strength</dt>
                <dd>
                  <span
                    className={`pill ${evidenceStrengthPillClass(explanation.evidence_strength)}`}
                  >
                    {explanation.evidence_strength}
                  </span>
                </dd>
              </div>
              <div>
                <dt className="label">Safety status</dt>
                <dd className="text-ink-800">{explanation.safety_status}</dd>
              </div>
              <div>
                <dt className="label">Routing reason</dt>
                <dd className="text-ink-800">{explanation.routed_reason}</dd>
              </div>
              <div>
                <dt className="label">Suggested verification</dt>
                <dd className="text-ink-800">{explanation.suggested_verification}</dd>
              </div>
            </dl>

            <p className="mt-4 border-t border-ink-200 pt-3 text-xs text-ink-400">
              This is a synthetic simulation. Evidence reflects reported data only — not
              a diagnosis, not a confirmed outbreak. Safety verification always requires
              human review before any action is taken.
            </p>
          </div>
        </div>
      )}
    </>
  )
}

const SAFETY_CHECK_LABELS: Record<string, string> = {
  village_scope_verified: 'Signal belongs to authorized village scope',
  reporting_period_validated: 'Reporting period validated',
  duplicate_records_checked: 'Duplicate records checked',
  sufficient_historical_window: 'Sufficient historical window',
  source_relationships_evaluated: 'Source relationships evaluated',
  missing_data_assessed: 'Missing data assessed',
  no_individual_diagnosis_generated: 'No individual diagnosis generated',
  no_autonomous_outbreak_declaration: 'No autonomous outbreak declaration',
  human_review_required: 'Human review required',
}

const SAFETY_BANNER: Record<
  string,
  { headline: string; detail: string; className: string; icon: string }
> = {
  PASS: {
    headline: 'PASS — Human Review Required',
    detail:
      'All nine safety checks passed. The signal still requires authorized officer review.',
    className: 'border-care-200 bg-care-50 text-care-800',
    icon: '✓',
  },
  INSUFFICIENT: {
    headline: 'INSUFFICIENT — Investigation requires human verification',
    detail:
      'Evidence is insufficient for escalation. Recommended: continue monitoring and verify with available sources.',
    className: 'border-amber-200 bg-amber-50 text-amber-800',
    icon: '!',
  },
  BLOCK: {
    headline: 'BLOCK — Safety conditions not satisfied',
    detail: 'One or more safety checks failed. This signal cannot proceed as-is.',
    className: 'border-red-200 bg-red-50 text-red-800',
    icon: '✕',
  },
}

/**
 * Phase 6 — the Safety Gate. Every one of the nine checklist rows and the
 * final banner is rendered purely from `safety` — the backend's own
 * `SafetyEngine.evaluate_latest()` output, embedded in the same
 * `/intelligence/` response the rest of this view already reads (task
 * §19/§21). Nothing here computes PASS/BLOCK/INSUFFICIENT, an evidence
 * strength, or a human-review flag — those three values, and only those
 * three, are the ones the task explicitly forbids calculating in React.
 *
 * The banner text is a small fixed lookup table over the three gate
 * values (not a template that could echo arbitrary upstream text), so an
 * injected phrase like "OUTBREAK DETECTED" can never become the headline
 * here even if it somehow reached this component — the only way it can
 * appear at all is quoted, in a `reason` string, as evidence of what the
 * Safety Engine caught and blocked.
 */
export function SafetyGatePanel({ safety }: { safety: SimulationSafetyResult }) {
  if (safety.gate_result === null) {
    // Phase 7 Replay: a week (typically week 1) with no persisted safety
    // result yet — a truthful "not evaluated" state, never a fabricated
    // PASS (task §6 boundaries carried into Replay).
    return (
      <div>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-ink-800">Safety Verification</h3>
          <SyntheticBadge />
        </div>
        <p className="mt-2 text-sm text-ink-500">
          {safety.not_evaluated_reason ?? 'Safety has not been evaluated for this week yet.'}
        </p>
      </div>
    )
  }

  const banner = SAFETY_BANNER[safety.gate_result] ?? SAFETY_BANNER.INSUFFICIENT

  return (
    <div>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-800">Safety Verification</h3>
        <SyntheticBadge />
      </div>

      <ul className="mt-2 space-y-1.5">
        {safety.checks.map((check) => (
          <li key={check.rule} className="flex items-start gap-2 text-sm">
            <span
              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${gateResultPillClass(
                check.result,
              )}`}
              aria-hidden="true"
            >
              {check.result === 'PASS' ? '✓' : check.result === 'BLOCK' ? '✕' : '!'}
            </span>
            <span className="min-w-0">
              <span className="text-ink-800">
                {SAFETY_CHECK_LABELS[check.rule] ?? check.rule}
              </span>
              <span className={`ml-2 pill ${gateResultPillClass(check.result)}`}>
                {check.result}
              </span>
              <p className="text-xs text-ink-500">{check.reason}</p>
            </span>
          </li>
        ))}
      </ul>

      <div
        className={`mt-3 rounded-md border px-3 py-2.5 ${banner.className}`}
        role="status"
      >
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span aria-hidden="true">{banner.icon}</span>
          {banner.headline}
        </div>
        <p className="mt-1 text-xs">{banner.detail}</p>
        <p className="mt-1 text-xs">
          Evidence strength: <span className="font-semibold">{safety.evidence_strength}</span>
        </p>
      </div>
    </div>
  )
}

/**
 * Phase 5 — Signal Intelligence. Reads exactly ONE object — normally
 * `useSimulationStore().intelligence` (the live/current week) — and hands
 * its five fields to the five components above; no component here calls
 * the intelligence endpoint itself (task §20).
 *
 * Phase 7 — Replay: when `override` is provided (a historical week's
 * already-computed payload from `GET .../replay/?week=N`), it is used
 * INSTEAD of the live `intelligence` — the exact same rendering, pointed
 * at a different, backend-chosen snapshot. This is the one place Replay
 * and the live view share code, by design: they show identical
 * structure, just for a different week, never two different UIs for "what
 * already happened" vs "what is happening now" (task §9).
 */
function IntelligenceView({
  override,
  viewingReplay = false,
}: {
  override?: SimulationIntelligence | null
  viewingReplay?: boolean
}) {
  const { intelligence, intelligenceLoading, intelligenceError } = useSimulationStore()
  const displayed = override ?? intelligence

  if (!displayed && !intelligenceLoading && !intelligenceError) return null

  const latestPrimarySignal =
    displayed && displayed.timeline.length > 0
      ? displayed.timeline[displayed.timeline.length - 1].primary_signal
      : null

  return (
    <div className="mt-4 border-t border-ink-200 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="label">
          {viewingReplay ? 'Signal Intelligence — Replay' : 'Signal Intelligence'}
        </div>
        <SyntheticBadge />
      </div>

      {intelligenceError && !viewingReplay && (
        <div className="mt-2">
          <ErrorNote message={intelligenceError} />
        </div>
      )}

      {intelligenceLoading && !displayed && !viewingReplay ? (
        <Loading label="Loading signal intelligence…" />
      ) : displayed ? (
        <div className="mt-3 space-y-4">
          <section>
            <h3 className="text-sm font-semibold text-ink-800">Community Signal Timeline</h3>
            <SignalTimelineChart timeline={displayed.timeline} />
          </section>
          <section className="border-t border-ink-200 pt-3">
            <h3 className="text-sm font-semibold text-ink-800">Evidence Constellation</h3>
            <EvidenceConstellation
              constellation={displayed.constellation}
              primarySignal={latestPrimarySignal}
            />
          </section>
          <section className="border-t border-ink-200 pt-3">
            <h3 className="text-sm font-semibold text-ink-800">Source Fusion</h3>
            <SourceFusionPanel sourceFusion={displayed.source_fusion} />
          </section>
          <section className="border-t border-ink-200 pt-3">
            <h3 className="text-sm font-semibold text-ink-800">Data Quality Lens</h3>
            <DataQualityLens dataQuality={displayed.data_quality} />
          </section>
          <section className="border-t border-ink-200 pt-3">
            <WhyAmISeeingThisPanel explanation={displayed.explanation} />
          </section>
          <section className="border-t border-ink-200 pt-3">
            <SafetyGatePanel safety={displayed.safety} />
          </section>
        </div>
      ) : null}
    </div>
  )
}

const REPLAY_SPEEDS = [0.5, 1, 2, 5] as const
const REPLAY_BASE_DELAY_MS = 1500

/**
 * The one place `minWeek`/`maxWeek`/`displayedWeek`/`isFirst`/`isLast` are
 * derived from `useSimulationStore()`'s `currentWeek`/`replayWeek` — both
 * `SimulationBottomBar` (the primary interactive transport) and
 * `ReplaySidebarSummary` (the left panel's compact readout) call this
 * SAME function rather than each re-deriving it, so there is exactly one
 * definition of "what week is currently being viewed" (task §15/§35).
 * `minWeek` is fixed at 1 for this UI-only bounds hint; the backend
 * independently enforces the real bound on every `GET .../replay/` call
 * regardless (task §6 of the Phase 7 spec).
 */
function deriveReplayBounds(currentWeek: number | null, replayWeek: number | null) {
  const minWeek = 1
  const maxWeek = currentWeek ?? minWeek
  const displayedWeek = replayWeek ?? maxWeek
  return {
    minWeek,
    maxWeek,
    displayedWeek,
    isFirst: displayedWeek <= minWeek,
    isLast: displayedWeek >= maxWeek,
  }
}

/**
 * Phase 7 — Signal Replay, primary transport controls. This is the
 * persistent bottom bar (task §7 of the layout spec) — it is the ONLY
 * place the auto-play `setTimeout` lives (never a second timer), and
 * every button below calls the exact same `useSimulationStore()` actions
 * `ReplaySidebarSummary`'s week-jump list also calls: `stepReplay`,
 * `setReplayPlaying`, `setReplaySpeed`. One source of truth for replay
 * position, playback state and speed — this component and the sidebar
 * summary are two presentations of that one state, never two engines.
 */
function SimulationBottomBar() {
  const {
    activeSession,
    currentWeek,
    replayWeek,
    replayLoading,
    replayPlaying,
    replaySpeed,
    stepReplay,
    setReplayPlaying,
    setReplaySpeed,
    liveStatus,
    liveRunning,
    livePaused,
    liveWeek,
    pauseLive,
    resumeLive,
    stopLive,
  } = useSimulationStore()

  const { minWeek, maxWeek, displayedWeek, isFirst, isLast } = deriveReplayBounds(
    currentWeek,
    replayWeek,
  )

  useEffect(() => {
    if (!replayPlaying) return undefined
    if (isLast) {
      setReplayPlaying(false)
      return undefined
    }
    const timer = window.setTimeout(() => {
      void stepReplay(Math.min(maxWeek, displayedWeek + 1))
    }, REPLAY_BASE_DELAY_MS / replaySpeed)
    return () => window.clearTimeout(timer)
  }, [replayPlaying, replaySpeed, displayedWeek, isLast, maxWeek, stepReplay, setReplayPlaying])

  if (!activeSession || currentWeek === null) return null

  // Live and Replay are mutually exclusive — the store disconnects Live the
  // moment Replay is entered (see `stepReplay`) — so this bar shows
  // whichever is actually active, never both (task's own persistent-
  // bottom-bar requirement: Live gets its own controls, Replay keeps its
  // existing Week/Previous/Play/Next/Reset/Speed exactly as before).
  if (liveStatus !== 'IDLE' && replayWeek === null) {
    return (
      <div
        className="card sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 px-4 py-3"
        role="toolbar"
        aria-label="Live simulation controls"
      >
        <span className="font-mono text-sm font-semibold tabular-nums text-ink-800">
          LIVE WEEK {liveWeek ?? currentWeek} / {activeSession.total_weeks}
        </span>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`pill font-semibold ${
              liveStatus === 'CONNECTED' ? 'bg-ink-800 text-white' : 'bg-ink-100 text-ink-600'
            }`}
          >
            {liveStatus === 'CONNECTED' ? '● LIVE' : LIVE_STATUS_LABEL[liveStatus]}
          </span>
          {livePaused && liveRunning && (
            <span className="pill bg-amber-100 text-amber-800 font-semibold">PAUSED</span>
          )}
          {liveRunning && !livePaused && (
            <button type="button" className="btn-ghost py-1.5" onClick={pauseLive}>
              ⏸ Pause
            </button>
          )}
          {liveRunning && livePaused && (
            <button type="button" className="btn-sentinel py-1.5" onClick={resumeLive}>
              ▶ Resume
            </button>
          )}
          {liveRunning && (
            <button type="button" className="btn-ghost py-1.5" onClick={stopLive}>
              ■ Stop
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div
      className="card sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-3 px-4 py-3"
      role="toolbar"
      aria-label="Simulation replay navigation"
    >
      <span className="font-mono text-sm font-semibold tabular-nums text-ink-800">
        Week {displayedWeek} / {maxWeek}
      </span>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-ghost py-1.5"
          disabled={isFirst || replayLoading}
          onClick={() => void stepReplay(Math.max(minWeek, displayedWeek - 1))}
        >
          ◀ Previous
        </button>
        <button
          type="button"
          className={isLast || replayLoading ? 'btn-ghost py-1.5' : 'btn-sentinel py-1.5'}
          disabled={isLast || replayLoading}
          onClick={() => setReplayPlaying(!replayPlaying)}
        >
          {replayPlaying ? '⏸ Pause' : '▶ Play'}
        </button>
        <button
          type="button"
          className="btn-ghost py-1.5"
          disabled={isLast || replayLoading}
          onClick={() => void stepReplay(Math.min(maxWeek, displayedWeek + 1))}
        >
          Next ▶
        </button>
        <button
          type="button"
          className="btn-ghost py-1.5"
          disabled={isFirst || replayLoading}
          onClick={() => void stepReplay(minWeek)}
        >
          ↻ Reset
        </button>
      </div>

      <div className="flex items-center gap-1.5 text-xs">
        <span className="text-ink-500">Speed:</span>
        {REPLAY_SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            aria-pressed={replaySpeed === speed}
            className={`pill ${
              replaySpeed === speed ? 'bg-sentinel-100 text-sentinel-700' : 'bg-ink-100 text-ink-600'
            }`}
            onClick={() => setReplaySpeed(speed)}
          >
            {speed}x
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * Phase 7 — Signal Replay, left-panel summary. Reads the SAME store state
 * as `SimulationBottomBar` above (via the same `deriveReplayBounds`) —
 * this is a secondary, informational presentation, not a second replay
 * engine. The per-week jump list and "Back to Live" button call the
 * identical `stepReplay`/`exitReplay` actions the bottom bar's
 * Previous/Next/Reset already use.
 */
function ReplaySidebarSummary() {
  const { activeSession, currentWeek, replayWeek, replaySpeed, stepReplay, exitReplay } =
    useSimulationStore()

  if (!activeSession || currentWeek === null) return null

  const { minWeek, maxWeek, displayedWeek } = deriveReplayBounds(currentWeek, replayWeek)

  return (
    <section>
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Replay</h3>
        {replayWeek !== null && (
          <button type="button" className="btn-ghost py-0.5 text-xs" onClick={exitReplay}>
            Back to Live
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-ink-500">
        Week <span className="font-mono font-semibold text-ink-800">{displayedWeek}</span> /{' '}
        {maxWeek} · Speed {replaySpeed}x
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {Array.from({ length: maxWeek - minWeek + 1 }, (_, index) => minWeek + index).map(
          (week) => (
            <button
              key={week}
              type="button"
              aria-current={week === displayedWeek}
              className={`rounded-md border px-1.5 py-0.5 font-mono text-[11px] tabular-nums ${
                week === displayedWeek
                  ? 'border-sentinel-500 bg-sentinel-50 font-semibold text-sentinel-700'
                  : 'border-ink-200 bg-white text-ink-600 hover:bg-ink-50'
              }`}
              onClick={() => (week === maxWeek ? exitReplay() : void stepReplay(week))}
            >
              W{week}
            </button>
          ),
        )}
      </div>
    </section>
  )
}

function formatWhatIfSourceValue(source: { value: number | null; reported: boolean } | undefined): string {
  if (!source || !source.reported) return 'not reported'
  return String(source.value)
}

/**
 * "Verify / What-If Information" — the right panel's "add hypothetical
 * source/verification input" form (Phase 7 What-If, task §36: "what would
 * happen if the synthetic inputs changed?"). `drafts`/`missing` are plain
 * component-local UI state — a draft the officer is editing, pre-filled
 * from the session's real current sources and reset whenever the session
 * or week changes. Submitting calls the store's `runWhatIf`, the ONLY
 * place a trend/relationship/evidence-strength/safety verdict is decided;
 * `SimulationResponsePanel` (rendered just below, in the same right panel)
 * and the center viewport's `WhatIfResultView` both read that same
 * `whatIfResult` to display it — this component owns the form, those only
 * read the result, so there is exactly one write path.
 */
function WhatIfControls() {
  const {
    activeSession,
    currentWeek,
    currentValues,
    whatIfLoading,
    whatIfError,
    runWhatIf,
    resetWhatIf,
  } = useSimulationStore()

  const realSources = useMemo(() => currentValues?.sources ?? [], [currentValues])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [missing, setMissing] = useState<Record<string, boolean>>({})

  useEffect(() => {
    const nextDrafts: Record<string, string> = {}
    const nextMissing: Record<string, boolean> = {}
    for (const source of realSources) {
      nextDrafts[source.source_type] = source.reported ? String(source.value ?? '') : ''
      nextMissing[source.source_type] = !source.reported
    }
    setDrafts(nextDrafts)
    setMissing(nextMissing)
    resetWhatIf()
    // Re-initialise the draft exactly when the officer moves to a
    // different session or a different week — not on every re-render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.session_id, currentWeek])

  if (!activeSession || currentValues === null) return null

  function handleRunWhatIf() {
    const overrides: Record<string, number | null> = {}
    for (const source of realSources) {
      if (missing[source.source_type]) {
        overrides[source.source_type] = null
        continue
      }
      const raw = drafts[source.source_type]
      const parsed = raw === '' || raw === undefined ? NaN : Number(raw)
      if (!Number.isNaN(parsed)) {
        overrides[source.source_type] = parsed
      }
    }
    void runWhatIf(overrides)
  }

  function handleResetInputs() {
    const nextDrafts: Record<string, string> = {}
    const nextMissing: Record<string, boolean> = {}
    for (const source of realSources) {
      nextDrafts[source.source_type] = source.reported ? String(source.value ?? '') : ''
      nextMissing[source.source_type] = !source.reported
    }
    setDrafts(nextDrafts)
    setMissing(nextMissing)
    resetWhatIf()
  }

  return (
    <section>
      <div className="space-y-2">
        {realSources.map((source) => (
          <div key={source.source_type} className="flex flex-wrap items-center gap-1.5">
            <span className="w-16 shrink-0 text-xs text-ink-700">{source.source_type}</span>
            <input
              type="number"
              min={0}
              className="input w-20 py-1 text-xs"
              disabled={missing[source.source_type]}
              value={drafts[source.source_type] ?? ''}
              onChange={(event) =>
                setDrafts((prev) => ({ ...prev, [source.source_type]: event.target.value }))
              }
            />
            <label className="flex items-center gap-1 text-[11px] text-ink-500">
              <input
                type="checkbox"
                checked={missing[source.source_type] ?? false}
                onChange={(event) =>
                  setMissing((prev) => ({ ...prev, [source.source_type]: event.target.checked }))
                }
              />
              Missing
            </label>
          </div>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-sentinel py-1.5 text-xs"
          disabled={whatIfLoading}
          onClick={handleRunWhatIf}
        >
          {whatIfLoading ? 'Evaluating hypothetical information…' : 'Apply Investigation Input'}
        </button>
        <button type="button" className="btn-ghost py-1.5 text-xs" onClick={handleResetInputs}>
          Reset Investigation Input
        </button>
      </div>
      {whatIfError && <p className="mt-2 text-xs text-red-700">{whatIfError}</p>}
    </section>
  )
}

/**
 * "Verify / What-If Information" result — the right panel's compact,
 * decision-facing read of `useSimulationStore().whatIfResult` (task
 * §14/§15/§39: distinguish ORIGINAL from HYPOTHETICAL, only report an
 * "Impact of Input" line the pipeline actually produced). No local state,
 * no computation of trend/evidence/safety — `supporting`/`conflicting` are
 * a pure filter over the already-computed `hypothetical.constellation`,
 * the exact same derivation `simulation.intelligence.build_intelligence`
 * already performs server-side for the real payload's
 * `explanation.sources_supporting/conflicting` (task §32: avoid duplicate
 * computation of anything NEW, not avoid re-deriving a display list from
 * data already shipped to the client).
 */
function deriveWhatIfSourceRelations(constellation: SimulationConstellationEntry[]) {
  return {
    supporting: constellation
      .filter((entry) => entry.relation === 'SUPPORTING')
      .map((entry) => entry.source),
    conflicting: constellation
      .filter((entry) => entry.relation === 'CONFLICTING')
      .map((entry) => entry.source),
  }
}

function SimulationResponsePanel() {
  const { whatIfResult } = useSimulationStore()

  if (!whatIfResult) {
    return <p className="text-xs text-ink-500">No investigation input has been applied yet.</p>
  }

  const { original, hypothetical, changed_sources: changedSources } = whatIfResult
  const { supporting, conflicting } = deriveWhatIfSourceRelations(hypothetical.constellation)
  const evidenceChanged = original.evidence_strength !== hypothetical.safety.evidence_strength
  const safetyChanged = original.gate_result !== hypothetical.safety.gate_result

  return (
    <div className="space-y-3">
      <span className="pill bg-violet-100 text-violet-700 font-semibold">HYPOTHETICAL</span>

      {hypothetical.trend === 'SIGNAL_DETECTED' && (
        <div className="rounded-lg border-2 border-red-300 bg-red-50 p-3">
          <div className="flex items-center gap-1.5">
            <span aria-hidden="true">🔴</span>
            <span className="text-sm font-semibold text-red-800">HYPOTHETICAL SIGNAL DETECTED</span>
          </div>
          <p className="mt-1 text-xs text-red-800">
            Simulation result only — the original session's own signal state is unchanged.
          </p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <span className="text-ink-500">Evidence</span>
        <span
          className={`pill w-fit ${evidenceStrengthPillClass(hypothetical.safety.evidence_strength ?? '')}`}
        >
          {hypothetical.safety.evidence_strength ?? '—'}
        </span>
        <span className="text-ink-500">Safety</span>
        <span className={`pill w-fit ${gateResultPillClass(hypothetical.safety.gate_result ?? '')}`}>
          {hypothetical.safety.gate_result ?? '—'}
        </span>
      </div>

      <div>
        <div className="label">Supporting</div>
        <p className="text-sm text-ink-800">{supporting.join(', ') || 'None'}</p>
      </div>
      <div>
        <div className="label">Conflicting</div>
        <p className="text-sm text-ink-800">{conflicting.join(', ') || 'None'}</p>
      </div>

      {(evidenceChanged || safetyChanged || changedSources.length > 0) && (
        <div className="rounded-md border border-ink-200 bg-ink-50 px-2.5 py-2">
          <div className="label">Impact of Input</div>
          {changedSources.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-xs">
              {changedSources.map((sourceType) => (
                <li key={sourceType} className="flex items-center justify-between">
                  <span className="text-ink-600">{sourceType}</span>
                  <span className="font-mono tabular-nums text-ink-800">
                    {formatWhatIfSourceValue(original.sources[sourceType])} →{' '}
                    {formatWhatIfSourceValue(hypothetical.sources[sourceType])}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {evidenceChanged && (
            <p className="mt-1 text-xs text-ink-600">
              Evidence: {original.evidence_strength ?? '—'} → {hypothetical.safety.evidence_strength ?? '—'}
            </p>
          )}
          {safetyChanged && (
            <p className="text-xs text-ink-600">
              Safety: {original.gate_result ?? '—'} → {hypothetical.safety.gate_result ?? '—'}
            </p>
          )}
        </div>
      )}

      {hypothetical.safety.gate_result === 'BLOCK' ? (
        <p className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-800">
          Signal processing is blocked pending safety verification.
        </p>
      ) : (
        hypothetical.suggested_next_step && (
          <p className="rounded-md border border-sentinel-200 bg-sentinel-50 px-2.5 py-1.5 text-xs text-sentinel-800">
            {RECOMMENDATION_SENTENCE[hypothetical.suggested_next_step]}
          </p>
        )
      )}
    </div>
  )
}

/**
 * Phase 7 — What-If, center-viewport pipeline/safety visualization. Pure
 * read of `useSimulationStore().whatIfResult` — no local state, no
 * computation: the decision-facing summary (evidence/safety/sources/
 * recommendation) lives in the right panel's `SimulationResponsePanel`
 * (task §37: center stays the technical multi-agent/safety visualization,
 * the right panel is the officer-facing response). One write path
 * (`WhatIfControls`, now in the right panel), two read paths.
 */
function WhatIfResultView() {
  const { whatIfError, whatIfResult } = useSimulationStore()
  const sectionRef = useRef<HTMLElement>(null)

  // The result renders below the pipeline/intelligence sections already in
  // the center viewport, which can be scrolled out of view — bring it into
  // view automatically so "Run What-If" always has a visible effect,
  // without changing what is computed or displayed (task's own "the
  // officer must be able to tell it happened" requirement).
  useEffect(() => {
    if (whatIfResult) {
      sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [whatIfResult])

  if (!whatIfError && !whatIfResult) return null

  return (
    <section ref={sectionRef} className="border-t border-ink-200 pt-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-800">What-If Result</h3>
        <SyntheticBadge />
      </div>

      {whatIfError && (
        <div className="mt-2">
          <ErrorNote message={whatIfError} />
        </div>
      )}

      {whatIfResult && (
        <div className="mt-3 space-y-4">
          <div className="rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800">
            <p className="font-semibold">HYPOTHETICAL SIMULATION</p>
            <p className="mt-1 text-xs">
              Hypothetical scenario — does not create a real alert or represent a confirmed
              outbreak.
            </p>
          </div>

          <section>
            <h3 className="text-sm font-semibold text-ink-800">Hypothetical Multi-Agent Pipeline</h3>
            <ul className="mt-1 space-y-1 text-xs">
              {whatIfResult.hypothetical.pipeline.map((stage) => (
                <li key={stage.agent} className="flex items-center justify-between">
                  <span className="text-ink-600">{STAGE_LABELS[stage.agent]}</span>
                  <span className="pill bg-care-100 text-care-700">{stage.status}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="border-t border-ink-200 pt-3">
            <h3 className="text-sm font-semibold text-ink-800">Hypothetical Safety Evaluation</h3>
            <SafetyGatePanel safety={whatIfResult.hypothetical.safety} />
          </section>
        </div>
      )}
    </section>
  )
}

// ===========================================================================
// COUNTERFACTUAL INVESTIGATION — Village A only. A structured "what would
// strengthen/weaken this signal?" layer over the exact same Phase 7
// What-If pipeline above: `runCounterfactual`/`resetCounterfactual` call
// `POST .../counterfactual/`, a thin village-gated wrapper around the
// identical `WhatIfEngine.run()` `WhatIfControls` already uses (see
// `simulation/views.py::SimulationCounterfactualView`). No second
// orchestrator, correlation, evidence, or safety algorithm exists here —
// every figure below is read straight off that same response shape, just
// with a few already-derivable comparison fields (supporting/conflicting/
// missing counts, trend) added server-side the same way Replay already
// reads an already-computed week.
// ===========================================================================

const COUNTERFACTUAL_VILLAGE_CODE = 'KVL'

interface CounterfactualOption {
  key: string
  sourceType: string
  group: 'strengthen' | 'weaken'
  label: string
  defaultValue: number | null
}

/** Built entirely from this session's own real current-week sources —
 *  never a hard-coded source list (task §22). A currently-reported source
 *  offers both an "increases" (strengthen) and a "remains stable" (weaken)
 *  option; a source that is not currently reported can only strengthen the
 *  signal by beginning to report — there is no sensible "stays not
 *  reported" counterfactual to offer for it (task §4: "only show options
 *  that make sense for the actual sources available"). "Remains stable"
 *  defaults to the previous week's own real value where one exists, so it
 *  is a genuine "no change" hypothesis, not an arbitrary number. */
function buildCounterfactualOptions(
  sources: SimulationSourceValue[],
  previousWeek: SimulationTimelinePoint | undefined,
): CounterfactualOption[] {
  const options: CounterfactualOption[] = []
  for (const source of sources) {
    const label = source.source_type.replace(/_/g, ' ')
    if (source.reported) {
      const current = source.value ?? 0
      options.push({
        key: `${source.source_type}-increase`,
        sourceType: source.source_type,
        group: 'strengthen',
        label: `${label} increases`,
        defaultValue: Math.max(current + 2, Math.round(current * 1.5)),
      })
      const previousValue = previousWeek?.sources.find(
        (s) => s.source_type === source.source_type,
      )?.value
      options.push({
        key: `${source.source_type}-stable`,
        sourceType: source.source_type,
        group: 'weaken',
        label: `${label} remains stable`,
        defaultValue: previousValue ?? current,
      })
    } else {
      options.push({
        key: `${source.source_type}-begins`,
        sourceType: source.source_type,
        group: 'strengthen',
        label: `${label} begins reporting`,
        defaultValue: 2,
      })
    }
  }
  return options
}

/** Compact +/- list of the actual original-vs-hypothetical differences —
 *  every line is a real figure from the response, nothing inferred. */
function counterfactualDiffLines(result: SimulationWhatIfResult): string[] {
  const { original, hypothetical } = result
  const lines: string[] = []
  const delta = (label: string, before: number, after: number) => {
    if (before === after) return
    const sign = after > before ? '+' : ''
    lines.push(`${label}: ${before} → ${after} (${sign}${after - before})`)
  }
  delta('Supporting sources', original.supporting_count, hypothetical.supporting_count)
  delta('Conflicting sources', original.conflicting_count, hypothetical.conflicting_count)
  delta('Missing sources', original.missing_count, hypothetical.missing_count)
  if (hypothetical.safety.evidence_strength !== original.evidence_strength) {
    lines.push(
      `Evidence: ${original.evidence_strength ?? '—'} → ${hypothetical.safety.evidence_strength ?? '—'}`,
    )
  }
  if (hypothetical.safety.gate_result !== original.gate_result) {
    lines.push(`Safety: ${original.gate_result ?? '—'} → ${hypothetical.safety.gate_result ?? '—'}`)
  }
  return lines
}

/** The raw source-level effect of the override, independent of whether it
 *  moved any derived metric (supporting/conflicting/evidence/safety) — a
 *  source's classification is direction-based (see
 *  `simulation.orchestrator._correlation`, which compares this week's value
 *  against the PREVIOUS week's, not against a fixed threshold), so a large
 *  hypothetical increase that doesn't reverse direction genuinely has no
 *  effect on supporting/conflicting counts even though it was fully applied.
 *  Without this list, that legitimate case was indistinguishable from the
 *  override never having reached the pipeline at all — this is the actual
 *  fix, not a change to the pipeline itself. */
function counterfactualSourceChangeLines(result: SimulationWhatIfResult): string[] {
  const { original, hypothetical, changed_sources: changedSources } = result
  return changedSources.map(
    (sourceType) =>
      `${sourceType}: ${formatWhatIfSourceValue(original.sources[sourceType])} → ` +
      `${formatWhatIfSourceValue(hypothetical.sources[sourceType])}`,
  )
}

/** Deterministic, template-only sentences built from the actual
 *  original-vs-hypothetical differences — never an LLM call, and never
 *  anything beyond what the backend already computed (task §10: "do not
 *  allow the LLM to invent facts about the result"). `changedSources.length
 *  === 0` is the ONLY genuine "nothing was applied" case (Section 26 of the
 *  task — e.g. a hypothetical value identical to the original). Once at
 *  least one source was actually overridden, the wording below never
 *  claims otherwise, even when that override happens to leave every
 *  derived metric unchanged. */
function counterfactualExplanation(result: SimulationWhatIfResult): string {
  const { original, hypothetical, changed_sources: changedSources } = result
  if (changedSources.length === 0) {
    return 'No hypothetical change was applied, so the assessment is unchanged.'
  }

  const supportingDelta = hypothetical.supporting_count - original.supporting_count
  const missingDelta = hypothetical.missing_count - original.missing_count
  const conflictingDelta = hypothetical.conflicting_count - original.conflicting_count
  const sentences: string[] = []

  if (supportingDelta > 0) {
    sentences.push(
      `The hypothetical change adds ${supportingDelta} more supporting source(s), so the ` +
        'signal is corroborated by more independent sources.',
    )
  } else if (supportingDelta < 0) {
    sentences.push(
      `The hypothetical change removes ${Math.abs(supportingDelta)} supporting source(s), so ` +
        'the signal has less independent corroboration.',
    )
  }
  if (conflictingDelta > 0) {
    sentences.push(
      'A hypothetical source now conflicts with the trend, reducing the strength of the evidence.',
    )
  }
  if (missingDelta > 0) {
    sentences.push(
      'A previously reported source is hypothetically missing, weakening reporting completeness.',
    )
  } else if (missingDelta < 0) {
    sentences.push(
      'A previously missing source hypothetically reports now, improving reporting completeness.',
    )
  }
  if (sentences.length === 0) {
    sentences.push(
      'The hypothetical value(s) below were applied, but they did not change which ' +
        'sources support or conflict with this signal, so the evidence assessment stays the same.',
    )
  }
  if (hypothetical.safety.gate_result !== original.gate_result) {
    sentences.push(
      `Safety moved from ${original.gate_result ?? '—'} to ${hypothetical.safety.gate_result ?? '—'} ` +
        'based on this hypothetical evidence.',
    )
  }
  return sentences.join(' ')
}

/** One Original-vs-Hypothetical row. `—` for a null value, never a
 *  fabricated placeholder. */
function ComparisonRow({
  label,
  original,
  hypothetical,
}: {
  label: string
  original: React.ReactNode
  hypothetical: React.ReactNode
}) {
  return (
    <tr>
      <td className="table-cell text-ink-600">{label}</td>
      <td className="table-cell font-mono">{original}</td>
      <td className="table-cell font-mono">{hypothetical}</td>
    </tr>
  )
}

function CounterfactualResult({ result }: { result: SimulationWhatIfResult }) {
  const { original, hypothetical } = result
  const diffLines = counterfactualDiffLines(result)

  return (
    <div className="mt-3 space-y-4">
      <div className="rounded-md border border-violet-200 bg-violet-50 px-3 py-2 text-sm text-violet-800">
        <p className="font-semibold">HYPOTHETICAL / SIMULATION ONLY</p>
        <p className="mt-1 text-xs">
          Scenario simulation — does not create a real alert and is never shown as an
          operational signal.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px]">
          <thead>
            <tr>
              <th className="table-head">Result</th>
              <th className="table-head">Original</th>
              <th className="table-head">Hypothetical</th>
            </tr>
          </thead>
          <tbody>
            <ComparisonRow label="Trend" original={original.trend ?? '—'} hypothetical={hypothetical.trend ?? '—'} />
            <ComparisonRow
              label="Supporting sources"
              original={original.supporting_count}
              hypothetical={hypothetical.supporting_count}
            />
            <ComparisonRow
              label="Conflicting sources"
              original={original.conflicting_count}
              hypothetical={hypothetical.conflicting_count}
            />
            <ComparisonRow
              label="Missing sources"
              original={original.missing_count}
              hypothetical={hypothetical.missing_count}
            />
            <ComparisonRow
              label="Evidence"
              original={
                <span className={`pill ${evidenceStrengthPillClass(original.evidence_strength ?? '')}`}>
                  {original.evidence_strength ?? '—'}
                </span>
              }
              hypothetical={
                <span
                  className={`pill ${evidenceStrengthPillClass(hypothetical.safety.evidence_strength ?? '')}`}
                >
                  {hypothetical.safety.evidence_strength ?? '—'}
                </span>
              }
            />
            <ComparisonRow
              label="Safety"
              original={
                <span className={`pill ${gateResultPillClass(original.gate_result ?? '')}`}>
                  {original.gate_result ?? '—'}
                </span>
              }
              hypothetical={
                <span className={`pill ${gateResultPillClass(hypothetical.safety.gate_result ?? '')}`}>
                  {hypothetical.safety.gate_result ?? '—'}
                </span>
              }
            />
            <ComparisonRow
              label="Human review"
              original={original.human_review_required ? 'Required' : '—'}
              hypothetical={hypothetical.safety.human_review_required ? 'Required' : '—'}
            />
          </tbody>
        </table>
      </div>

      {result.changed_sources.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            Hypothetical values applied
          </h4>
          <ul className="mt-1 space-y-0.5 text-xs text-ink-700">
            {counterfactualSourceChangeLines(result).map((line) => (
              <li key={line} className="font-mono tabular-nums">
                {line}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
          Why did the assessment change?
        </h4>
        <p className="mt-1 text-sm text-ink-800">{counterfactualExplanation(result)}</p>
      </section>

      {diffLines.length > 0 && (
        <section>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">
            What changed?
          </h4>
          <ul className="mt-1 space-y-0.5 text-xs text-ink-700">
            {diffLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      <details className="border-t border-ink-200 pt-3">
        <summary className="label cursor-pointer select-none">Safety detail</summary>
        <div className="mt-2">
          <SafetyGatePanel safety={hypothetical.safety} />
        </div>
      </details>
    </div>
  )
}

function CounterfactualControls({ options }: { options: CounterfactualOption[] }) {
  const { activeSession, currentWeek, counterfactualLoading, runCounterfactual, resetCounterfactual } =
    useSimulationStore()
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [values, setValues] = useState<Record<string, string>>({})

  useEffect(() => {
    setSelected({})
    const nextValues: Record<string, string> = {}
    for (const option of options) nextValues[option.key] = String(option.defaultValue ?? '')
    setValues(nextValues)
    resetCounterfactual()
    // Re-initialise exactly when the officer moves to a different session
    // or week — not on every re-render, and not merely because a new
    // option object was recreated with the same underlying sources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.session_id, currentWeek])

  function toggle(option: CounterfactualOption) {
    setSelected((prev) => {
      const next = { ...prev, [option.key]: !prev[option.key] }
      // A source can be hypothetically strengthened OR weakened, never
      // both at once — checking one clears the other option for the same
      // source rather than leaving an ambiguous combined override.
      if (next[option.key]) {
        for (const other of options) {
          if (other.sourceType === option.sourceType && other.key !== option.key) {
            next[other.key] = false
          }
        }
      }
      return next
    })
  }

  function handleRun() {
    const overrides: Record<string, number | null> = {}
    for (const option of options) {
      if (!selected[option.key]) continue
      const raw = values[option.key]
      const parsed = raw === '' || raw === undefined ? NaN : Number(raw)
      overrides[option.sourceType] = Number.isNaN(parsed) ? null : parsed
    }
    void runCounterfactual(overrides)
  }

  function handleReset() {
    setSelected({})
    resetCounterfactual()
  }

  const strengthenOptions = options.filter((o) => o.group === 'strengthen')
  const weakenOptions = options.filter((o) => o.group === 'weaken')
  const anySelected = options.some((o) => selected[o.key])

  function renderOption(option: CounterfactualOption) {
    const checked = selected[option.key] ?? false
    return (
      <li key={option.key} className="flex flex-wrap items-center gap-2">
        <label className="flex flex-1 min-w-[160px] items-center gap-1.5 text-xs text-ink-700">
          <input type="checkbox" checked={checked} onChange={() => toggle(option)} />
          {option.label}
        </label>
        {checked && (
          <label className="flex items-center gap-1 text-[11px] text-ink-500">
            Hypothetical value
            <input
              type="number"
              className="input w-20 py-1 text-xs"
              value={values[option.key] ?? ''}
              onChange={(event) =>
                setValues((prev) => ({ ...prev, [option.key]: event.target.value }))
              }
            />
          </label>
        )}
      </li>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="label">What could strengthen this signal?</div>
        {strengthenOptions.length === 0 ? (
          <p className="text-xs text-ink-400">No sources available to strengthen this week.</p>
        ) : (
          <ul className="mt-1 space-y-1.5">{strengthenOptions.map(renderOption)}</ul>
        )}
      </div>
      <div>
        <div className="label">What could weaken this signal?</div>
        {weakenOptions.length === 0 ? (
          <p className="text-xs text-ink-400">No sources available to weaken this week.</p>
        ) : (
          <ul className="mt-1 space-y-1.5">{weakenOptions.map(renderOption)}</ul>
        )}
      </div>

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          className="btn-sentinel py-1.5 text-xs"
          disabled={!anySelected || counterfactualLoading}
          onClick={handleRun}
        >
          {counterfactualLoading ? 'Running…' : 'Run Counterfactual'}
        </button>
        <button type="button" className="btn-ghost py-1.5 text-xs" onClick={handleReset}>
          Reset Counterfactual
        </button>
      </div>
    </div>
  )
}

/**
 * Village A only (task §3) — a deliberate product-scoping decision, not a
 * technical one: the underlying pipeline is identical for every village.
 * Gated on the session's own `village_code`, never a frontend village
 * selector, and backed by the same gate `SimulationCounterfactualView`
 * enforces server-side (task §3/§20). Renders nothing at all for any other
 * village, rather than a disabled placeholder — Village B officers should
 * see no trace of this feature.
 *
 * Disabled (with a concise reason, never silently) while browsing Replay
 * (task §17 — the endpoint always targets the session's real current week,
 * never an arbitrary replayed one, exactly like What-If above) or while
 * Live Emergence is actively streaming (task §18).
 */
function CounterfactualInvestigationSection() {
  const { activeSession, currentValues, intelligence, replayWeek, liveStatus, counterfactualError } =
    useSimulationStore()

  if (!activeSession || activeSession.village_code !== COUNTERFACTUAL_VILLAGE_CODE) return null
  if (!currentValues) return null

  const disabledReason =
    replayWeek !== null
      ? 'Exit Replay to run a counterfactual investigation on the current week.'
      : liveStatus !== 'IDLE'
        ? 'Pause or stop Live Emergence to run a counterfactual investigation.'
        : null

  const realSources = currentValues.sources
  const previousWeek =
    intelligence && intelligence.timeline.length > 1
      ? intelligence.timeline[intelligence.timeline.length - 2]
      : undefined
  const options = buildCounterfactualOptions(realSources, previousWeek)

  const supporting = intelligence?.explanation.sources_supporting ?? []
  const conflicting = intelligence?.explanation.sources_conflicting ?? []

  return (
    <section className="border-t border-ink-200 pt-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink-800">Counterfactual Investigation</h3>
        <SyntheticBadge />
      </div>
      <p className="mt-1 text-xs text-ink-500">
        What could change the evidence for this signal?
      </p>

      <div className="mt-3 rounded-md border border-ink-200 bg-ink-50 px-3 py-2">
        <div className="label">Current evidence</div>
        <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-ink-700">
          <span>
            Supporting: <span className="font-medium">{supporting.join(', ') || 'None'}</span>
          </span>
          <span>
            Conflicting: <span className="font-medium">{conflicting.join(', ') || 'None'}</span>
          </span>
        </div>
      </div>

      {disabledReason ? (
        <p className="mt-3 text-xs text-ink-500">{disabledReason}</p>
      ) : (
        <div className="mt-3">
          <CounterfactualControls options={options} />
        </div>
      )}

      {counterfactualError && (
        <div className="mt-2">
          <ErrorNote message={counterfactualError} />
        </div>
      )}

      <CounterfactualResultSection />
    </section>
  )
}

function CounterfactualResultSection() {
  const { counterfactualResult } = useSimulationStore()
  const sectionRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (counterfactualResult) {
      sectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [counterfactualResult])

  if (!counterfactualResult) return null

  return (
    <div ref={sectionRef}>
      <CounterfactualResult result={counterfactualResult} />
    </div>
  )
}

/**
 * Right panel — a compact pointer to the detailed result in the center
 * viewport (task §21: "do not duplicate the full comparison in both").
 * Renders nothing when no counterfactual has been run.
 */
function CounterfactualSummaryPanel() {
  const { counterfactualResult } = useSimulationStore()
  if (!counterfactualResult) return null

  const { original, hypothetical } = counterfactualResult
  const diffLines = counterfactualDiffLines(counterfactualResult)

  return (
    <details className="border-t border-ink-200 pt-3" open>
      <summary className="label cursor-pointer select-none">Counterfactual</summary>
      <div className="mt-2 space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <span className="text-ink-500">Original</span>
          <span className={`pill ${evidenceStrengthPillClass(original.evidence_strength ?? '')}`}>
            {original.evidence_strength ?? '—'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-ink-500">Hypothetical</span>
          <span
            className={`pill ${evidenceStrengthPillClass(hypothetical.safety.evidence_strength ?? '')}`}
          >
            {hypothetical.safety.evidence_strength ?? '—'}
          </span>
        </div>
        <p className="text-ink-600">Changed because: {diffLines[0] ?? 'No change applied.'}</p>
        <div className="flex items-center justify-between">
          <span className="text-ink-500">Safety</span>
          <span className={`pill ${gateResultPillClass(hypothetical.safety.gate_result ?? '')}`}>
            {hypothetical.safety.gate_result ?? '—'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-ink-500">Human review</span>
          <span className="text-ink-800">
            {hypothetical.safety.human_review_required ? 'Required' : '—'}
          </span>
        </div>
      </div>
    </details>
  )
}

/**
 * Left panel, "SIMULATION" section — the core Phase 3/4/6 transport: the
 * SAME `advanceSession`/`resetSession` actions the page has always used,
 * just relocated so they are reachable without scrolling (task's whole
 * point). Deliberately separate from `SimulationBottomBar` above:
 * "Next Week" COMPUTES a new week (runs the real pipeline); the bottom
 * bar's "Next" BROWSES an already-computed week (Replay) — two different
 * actions that happen to share a word, kept visibly distinct so an
 * officer never confuses "advance the simulation" with "look at history".
 */
/**
 * Phase 8 — Live Streaming controls, left panel. Opt-in on purpose: a
 * session starts in the same plain REST "Next Week (Advance)" mode every
 * earlier phase already used, and connecting the WebSocket is a deliberate
 * additional action, never automatic — so a session the officer never
 * intends to stream live never opens a socket at all (task's own resource-
 * safety requirement).
 */
const LIVE_STATUS_LABEL: Record<string, string> = {
  IDLE: 'Not connected',
  CONNECTING: 'Connecting…',
  CONNECTED: 'Connected',
  DISCONNECTED: 'Disconnected',
  RECONNECTING: 'Reconnecting…',
  ERROR: 'Connection error',
}

function LiveControls() {
  const {
    liveStatus,
    liveRunning,
    livePaused,
    liveError,
    activeSession,
    connectLive,
    disconnectLive,
    startLive,
    pauseLive,
    resumeLive,
    stopLive,
  } = useSimulationStore()

  if (!activeSession || activeSession.is_complete) return null

  const connected = liveStatus === 'CONNECTED'
  const busy = liveStatus === 'CONNECTING' || liveStatus === 'RECONNECTING'

  return (
    <section className="border-t border-ink-200 pt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">
        Live Streaming
      </h3>

      <div className="mt-2 flex items-center gap-2 text-xs">
        <span
          className={`pill font-medium ${
            connected
              ? 'bg-ink-800 text-white'
              : liveStatus === 'ERROR'
                ? 'bg-red-100 text-red-700'
                : 'bg-ink-100 text-ink-600'
          }`}
        >
          {connected ? '● LIVE' : LIVE_STATUS_LABEL[liveStatus]}
        </span>
        {livePaused && connected && (
          <span className="pill bg-amber-100 text-amber-800 font-medium">PAUSED</span>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        {liveStatus === 'IDLE' || liveStatus === 'DISCONNECTED' || liveStatus === 'ERROR' ? (
          <button type="button" className="btn-sentinel py-1.5 text-xs" onClick={connectLive}>
            {liveStatus === 'ERROR' ? 'Reconnect' : 'Go Live'}
          </button>
        ) : (
          <>
            {connected && !liveRunning && (
              <button type="button" className="btn-sentinel py-1.5 text-xs" onClick={startLive}>
                Start
              </button>
            )}
            {connected && liveRunning && !livePaused && (
              <button type="button" className="btn-ghost py-1.5 text-xs" onClick={pauseLive}>
                Pause
              </button>
            )}
            {connected && liveRunning && livePaused && (
              <button type="button" className="btn-sentinel py-1.5 text-xs" onClick={resumeLive}>
                Resume
              </button>
            )}
            {connected && liveRunning && (
              <button type="button" className="btn-ghost py-1.5 text-xs" onClick={stopLive}>
                Stop
              </button>
            )}
            <button type="button" className="btn-ghost py-1.5 text-xs" onClick={disconnectLive} disabled={busy}>
              Disconnect
            </button>
          </>
        )}
      </div>

      {liveError && (
        <div className="mt-2">
          <ErrorNote message={liveError} />
        </div>
      )}
    </section>
  )
}

function SimulationAdvanceControls() {
  const { loading, error, activeSession, advanceSession, resetSession } = useSimulationStore()

  if (!activeSession) return null
  const isComplete = activeSession.is_complete

  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Simulation</h3>
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          className="btn-sentinel py-1.5 text-xs"
          disabled={loading || isComplete}
          onClick={() => void advanceSession()}
        >
          {loading ? 'Loading…' : 'Next Week (Advance)'}
        </button>
        <button type="button" className="btn-ghost py-1.5 text-xs" onClick={resetSession}>
          Reset Simulation
        </button>
      </div>
      {error && (
        <div className="mt-2">
          <ErrorNote message={error} />
        </div>
      )}
      {isComplete && (
        <p className="mt-2 rounded-md border border-care-200 bg-care-50 px-2.5 py-1.5 text-xs text-care-800">
          Simulation complete — synthetic replay only, no operational alert or
          investigation was created.
        </p>
      )}
    </section>
  )
}

/** Left panel, "SESSION" section — the same scenario/status/week fields
 *  `SessionRunnerPanel` has always read, just moved here. */
function SessionInfoSummary() {
  const { activeSession, currentWeek, currentValues } = useSimulationStore()
  if (!activeSession || currentValues === null) return null

  return (
    <section className="border-t border-ink-200 pt-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">Session</h3>
      <dl className="mt-2 space-y-1.5 text-xs">
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Scenario</dt>
          <dd className="font-medium text-ink-800">{activeSession.scenario_name}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Status</dt>
          <dd className="font-medium text-ink-800">{activeSession.status_display}</dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Week</dt>
          <dd className="font-mono font-medium text-ink-800">
            {currentWeek} / {activeSession.total_weeks}
          </dd>
        </div>
        <div className="flex items-center justify-between">
          <dt className="text-ink-500">Scenario status</dt>
          <dd className="font-medium text-ink-800">{currentValues.status_label}</dd>
        </div>
      </dl>
    </section>
  )
}

/**
 * Left control panel — everything an officer needs to DRIVE the
 * simulation (task §4). Every section below is a thin presentational
 * regrouping of components that already existed; none of them hold or
 * duplicate simulation state themselves.
 */
function SimulationControlPanel() {
  return (
    <div className="space-y-4">
      <SimulationAdvanceControls />
      <LiveControls />
      <div className="border-t border-ink-200 pt-3">
        <ReplaySidebarSummary />
      </div>
      <SessionInfoSummary />
    </div>
  )
}

/** Center viewport, "Current Week / Community Signal Summary" — the same
 *  "current synthetic signals" / "source reports this week" blocks
 *  `SessionRunnerPanel` has always shown, unchanged, just relocated to
 *  the top of the scrollable center column. */
function CurrentWeekSignalSummary() {
  const { currentValues } = useSimulationStore()
  if (currentValues === null) return null

  const categories = Object.entries(currentValues.categories)

  return (
    <section>
      <h3 className="text-sm font-semibold text-ink-800">Community Signal Summary</h3>
      <div className="mt-2 grid gap-4 sm:grid-cols-2">
        <div>
          <div className="label">Current synthetic signals</div>
          <ul className="mt-1 space-y-1">
            {categories.map(([label, value]) => (
              <li key={label} className="flex items-center justify-between text-sm">
                <span className="text-ink-600">{label}</span>
                <span className="font-mono tabular-nums text-ink-800">{value}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="label">Source reports this week</div>
          <ul className="mt-1 space-y-1">
            {currentValues.sources.map((source) => (
              <li
                key={source.source_type}
                className="flex items-center justify-between text-sm"
              >
                <span className="text-ink-600">{source.source_type}</span>
                <span className="font-mono tabular-nums text-ink-800">
                  {source.reported ? (
                    source.value
                  ) : (
                    <span className="italic text-ink-400">not submitted</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

/**
 * Right panel — "Officer Intelligence & Response". A compact, secondary
 * read of the SAME live-or-replay intelligence the center viewport already
 * shows, PLUS the officer-facing What-If input/response (moved here from
 * the left control panel so the officer can add hypothetical investigation
 * input and see the pipeline's actual response in one place). Every field
 * is looked up directly from `intelligence`/`replayIntelligence`/
 * `whatIfResult` — nothing here runs a second simulation or recommendation
 * algorithm. Two fields the current API genuinely does not provide yet —
 * investigation priority and investigation status, both Phase 9 concepts —
 * are labelled as such rather than fabricated (task §10: "do not invent a
 * successful safety result").
 */
/**
 * Phase 9 — "Investigate Signal" (task §29). Opens the Investigation
 * Notebook for the active session's current signal. Disabled when the
 * Safety Gate is BLOCK — matching the notebook's own hard rule (task §5:
 * "Investigation can proceed for PASS/INSUFFICIENT; must be blocked for
 * BLOCK") a step earlier, so the officer never even reaches a workspace
 * they can't act in.
 */
function InvestigateSignalAction({
  safetyGateResult,
}: {
  safetyGateResult: SimulationSafetyResult['gate_result']
}) {
  const navigate = useNavigate()
  const { activeSession } = useSimulationStore()
  if (!activeSession) return null

  const blocked = safetyGateResult === 'BLOCK'

  return (
    <section className="border-t border-ink-200 pt-3">
      <button
        type="button"
        className="btn-sentinel w-full py-2 text-sm"
        disabled={blocked}
        title={blocked ? 'Investigation is unavailable while the Safety Gate is BLOCK.' : undefined}
        onClick={() => navigate(`/officer/simulation/investigation/${activeSession.session_id}`)}
      >
        Investigate Signal
      </button>
      {blocked && (
        <p className="mt-1 text-[11px] text-red-700">
          Unavailable while Safety = BLOCK. Review the Safety Gate section for the reason.
        </p>
      )}
    </section>
  )
}

/** Reads the Phase 9 investigation state ONLY if it has already been
 *  loaded for THIS session (never fetched here — merely viewing this
 *  panel must not create an investigation row; only the explicit
 *  "Investigate Signal" action does, task §5/§50). */
function InvestigationPriorityHint() {
  const { investigation, activeSession } = useSimulationStore()
  if (investigation && investigation.overview.session_id === activeSession?.session_id) {
    return <p className="text-sm text-ink-800">{investigation.overview.investigation_priority || '—'}</p>
  }
  return <p className="text-xs text-ink-500">Open the Investigation Notebook to see prioritisation.</p>
}

function InvestigationStatusHint() {
  const { investigation, activeSession } = useSimulationStore()
  if (investigation && investigation.overview.session_id === activeSession?.session_id) {
    return <p className="text-sm text-ink-800">{investigation.status_display}</p>
  }
  return <p className="text-xs text-ink-500">No investigation opened for this session yet.</p>
}

/** Reads exactly `intelligence.timeline` (Phase 5, unchanged) — never a
 *  second timeline/trend computation. `current`/`previous` are the SAME
 *  two values `simulation.orchestrator._classify_trend` itself compared
 *  when it decided the trend (task §9): the latest and second-latest
 *  revealed week's value for the session's own primary signal. `percent`
 *  is a pure display derivation, only computed when the denominator is a
 *  real positive number (task §9: "do not show misleading percentages
 *  when the denominator is zero or missing"). */
function deriveSignalReading(timeline: SimulationTimelinePoint[]) {
  const latest = timeline.length ? timeline[timeline.length - 1] : null
  const previous = timeline.length >= 2 ? timeline[timeline.length - 2] : null
  const current = latest?.value ?? null
  const previousValue = previous?.value ?? null
  const change = current !== null && previousValue !== null ? current - previousValue : null
  const percent =
    change !== null && previousValue !== null && previousValue > 0
      ? Math.round((change / previousValue) * 100)
      : null
  return { latest, current, previousValue, change, percent }
}

/** Deterministic PHRASING only — the recommendation CATEGORY itself is
 *  `suggested_next_step`, computed entirely on the backend by the exact
 *  same Phase 9/10 `suggested_decision()` the Investigation Notebook uses
 *  (task §12: "the recommendation should be deterministic... if an LLM is
 *  used only to phrase the recommendation, it must never change the
 *  underlying recommendation category" — no LLM is used here at all, but
 *  the same separation applies: this map only turns an already-decided
 *  category into a sentence). */
const RECOMMENDATION_SENTENCE: Record<InvestigationDecisionValue, string> = {
  CONTINUE_MONITORING: 'Continue routine monitoring; evidence does not yet warrant further action.',
  REQUEST_MORE_DATA: 'Request additional reporting from relevant sources before drawing a conclusion.',
  VERIFY_WITH_PHC: 'Review the conflicting source reports and verify the signal with PHC.',
  CONDUCT_FIELD_VERIFICATION:
    'Verify the signal with PHC and conduct field verification before further escalation.',
  REQUEST_LABORATORY_VERIFICATION: 'Request laboratory verification to confirm the reported signal.',
  ESCALATE_FOR_HUMAN_REVIEW: 'Escalate for human public-health review.',
  CLOSE_AS_INSUFFICIENT_EVIDENCE: 'Continue monitoring; evidence remains insufficient to escalate.',
}

/** Task §16/§42's "ALERTS" header block — merges the previous "Current
 *  Signal" section with the new high-signal state, rather than showing
 *  both (task §34: "do not unnecessarily duplicate information"). Red
 *  styling appears ONLY when the EXISTING, unmodified Signal Analysis
 *  stage already classified this week as `SIGNAL_DETECTED` (task §2/§27:
 *  "the state must be DERIVED, not manually toggled") — every other
 *  status (NORMAL/STABLE/INCREASING) keeps the neutral presentation this
 *  section already had. */
function SignalStateBanner({
  intelligence,
  week,
}: {
  intelligence: SimulationIntelligence
  week: number | null
}) {
  const { latest, current, previousValue, change, percent } = deriveSignalReading(
    intelligence.timeline,
  )
  const detected = latest?.status === 'SIGNAL_DETECTED'

  return (
    <section
      role={detected ? 'alert' : undefined}
      className={
        detected
          ? 'rounded-lg border-2 border-red-300 bg-red-50 p-3'
          : 'rounded-lg border border-ink-200 bg-white p-3'
      }
    >
      <div className="flex items-center gap-1.5">
        {detected && <span aria-hidden="true">🔴</span>}
        <span className={`text-sm font-semibold ${detected ? 'text-red-800' : 'text-ink-800'}`}>
          {detected ? 'SIGNAL DETECTED' : 'Current Signal'}
        </span>
      </div>
      <p className={`mt-1 text-sm ${detected ? 'text-red-800' : 'text-ink-700'}`}>
        {intelligence.explanation.signal}
      </p>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-ink-500">Week</dt>
          <dd className="font-mono font-medium text-ink-800">{week ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-ink-500">Current</dt>
          <dd className="font-mono font-medium text-ink-800">{current ?? '—'}</dd>
        </div>
        <div>
          <dt className="text-ink-500">Previous</dt>
          <dd className="font-mono font-medium text-ink-800">{previousValue ?? '—'}</dd>
        </div>
      </dl>
      {change !== null && (
        <p className="mt-1 text-xs text-ink-500">
          Change: {change >= 0 ? '+' : ''}
          {change}
          {percent !== null && ` (${percent >= 0 ? '+' : ''}${percent}%)`}
        </p>
      )}
    </section>
  )
}

/** Task §10-§13's "RECOMMENDED NEXT STEP" — a standing section (useful in
 *  every state, not only when a red alert fires), but Safety remains
 *  authoritative over it: BLOCK always overrides with the existing safety
 *  wording (task §13 — never implies the officer may proceed), never the
 *  investigation-guidance text a BLOCKed week's `suggested_next_step`
 *  would otherwise be (it is always `''` for BLOCK regardless, per
 *  `simulation.investigation.suggested_decision`, but this is re-checked
 *  here directly against `safety.gate_result` too — belt-and-braces, the
 *  same "never trust a single layer" convention this codebase already
 *  uses everywhere else). */
function RecommendedNextStep({
  suggestedNextStep,
  gateResult,
}: {
  suggestedNextStep: InvestigationDecisionValue | ''
  gateResult: SimulationSafetyGateResult | null
}) {
  if (gateResult === 'BLOCK') {
    return (
      <section className="border-t border-ink-200 pt-3">
        <div className="label">Recommended Next Step</div>
        <p className="rounded-md border border-red-200 bg-red-50 px-2.5 py-1.5 text-xs text-red-800">
          Signal processing is blocked pending safety verification.
        </p>
      </section>
    )
  }

  if (!suggestedNextStep) return null

  return (
    <section className="border-t border-ink-200 pt-3">
      <div className="label">Recommended Next Step</div>
      <p className="rounded-md border border-sentinel-200 bg-sentinel-50 px-2.5 py-1.5 text-xs text-sentinel-800">
        {RECOMMENDATION_SENTENCE[suggestedNextStep]}
      </p>
    </section>
  )
}

function SimulationAlertPanel() {
  const { intelligence, replayWeek, replayIntelligence, currentWeek, whatIfResult, whatIfError } =
    useSimulationStore()
  const displayed = replayWeek !== null ? replayIntelligence : intelligence

  if (!displayed) {
    return <Empty>Alert intelligence appears once this session has data to show.</Empty>
  }

  const safety = displayed.safety
  const explanation = displayed.explanation

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-600">
          Officer Intelligence &amp; Response
        </h3>
        <SyntheticBadge />
      </div>

      <SignalStateBanner intelligence={displayed} week={replayWeek ?? currentWeek} />

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Evidence Strength</div>
        <span className={`pill ${evidenceStrengthPillClass(explanation.evidence_strength)}`}>
          {explanation.evidence_strength}
        </span>
      </section>

      <details
        className="border-t border-ink-200 pt-3"
        open={whatIfResult !== null || whatIfError !== null}
      >
        <summary className="label cursor-pointer select-none">Verify / What-If Information</summary>
        <div className="mt-2 space-y-3">
          <p className="text-xs text-ink-500">
            Test how additional or missing information could change the evidence for this
            signal. This does not change the original simulation.
          </p>
          <WhatIfControls />
          <SimulationResponsePanel />
        </div>
      </details>

      <CounterfactualSummaryPanel />

      <RecommendedNextStep
        suggestedNextStep={displayed.suggested_next_step}
        gateResult={safety.gate_result}
      />

      <InvestigateSignalAction safetyGateResult={safety.gate_result} />

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Investigation Priority</div>
        <InvestigationPriorityHint />
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Supporting Sources</div>
        <p className="text-sm text-ink-800">
          {explanation.sources_supporting.join(', ') || 'None'}
        </p>
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Conflicting Sources</div>
        <p className="text-sm text-ink-800">
          {explanation.sources_conflicting.join(', ') || 'None'}
        </p>
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Data Quality</div>
        <p className="text-sm text-ink-800">{displayed.data_quality.completeness_pct}% complete</p>
        {displayed.data_quality.missing.length > 0 && (
          <p className="mt-1 text-xs text-amber-700">
            {displayed.data_quality.missing.length} missing report(s) — see Data Quality Lens.
          </p>
        )}
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Why This Alert?</div>
        <p className="text-xs text-ink-600">{explanation.routed_reason}</p>
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Safety Status</div>
        {safety.gate_result === null ? (
          <p className="text-xs text-ink-500">
            {safety.not_evaluated_reason ?? 'Not yet evaluated for this week.'}
          </p>
        ) : (
          <span className={`pill ${gateResultPillClass(safety.gate_result)}`}>
            {safety.gate_result}
          </span>
        )}
      </section>

      <section className="border-t border-ink-200 pt-3">
        <div className="label">Investigation Status</div>
        <InvestigationStatusHint />
      </section>
    </div>
  )
}

/**
 * The command-center workspace: LEFT controls / CENTER scrollable
 * intelligence / RIGHT alert panel / persistent BOTTOM replay bar (task
 * §2). Every piece below reuses the exact same `useSimulationStore()`
 * actions and API-backed state the page has always used — this component
 * only recomposes their presentation into three panels instead of one
 * long stack; no simulation state, API call, or handler is duplicated
 * anywhere in this file.
 *
 * Height strategy: each of the three panels is independently capped at
 * `calc(100vh - 15rem)` (a fixed, resolution-independent CHROME offset —
 * PortalLayout's own sticky nav plus this page's own header/status strip
 * — subtracted from the actual viewport height, never a hardcoded pixel
 * height for the content itself) and scrolls internally past that. This
 * deliberately does not depend on `PortalLayout`'s own height chain
 * (confirmed to NOT propagate a real height down to this page — see the
 * layout survey this task started with): `vh` units resolve against the
 * browser viewport directly, so the cap is correct regardless of what
 * height (if any) the ancestor chain provides. The bottom bar is also
 * `position: sticky; bottom: 0`, a second, independent guarantee that it
 * stays on-screen even if this estimate runs a little short on an
 * unusually small window — never `position: fixed`, which would sit on
 * top of the portal's own footer disclaimer instead of stacking after it.
 */
/** Unambiguous "what am I looking at right now" indicator (task's own
 *  explicit requirement — LIVE / REPLAY / WHAT-IF must never be ambiguous).
 *  Replay wins visually over Live when both happen to be non-idle, matching
 *  the store's own "never mixed" rule (opening Replay disconnects Live). */
function ModeIndicator() {
  const { replayWeek, liveStatus, whatIfResult, counterfactualResult } = useSimulationStore()

  if (replayWeek !== null) {
    return <span className="pill bg-amber-100 text-amber-800 font-semibold">◷ REPLAY</span>
  }
  if (liveStatus !== 'IDLE') {
    const label =
      liveStatus === 'CONNECTED'
        ? '● LIVE SIMULATION'
        : liveStatus === 'ERROR'
          ? '● LIVE — ERROR'
          : `● LIVE — ${LIVE_STATUS_LABEL[liveStatus]}`
    return (
      <span
        className={`pill font-semibold ${
          liveStatus === 'CONNECTED' ? 'bg-ink-800 text-white' : 'bg-ink-100 text-ink-600'
        }`}
      >
        {label}
      </span>
    )
  }
  if (counterfactualResult) {
    return <span className="pill bg-violet-100 text-violet-700 font-semibold">◆ COUNTERFACTUAL</span>
  }
  if (whatIfResult) {
    return <span className="pill bg-ink-100 text-ink-600 font-semibold">◆ WHAT-IF</span>
  }
  return null
}

function SessionRunnerPanel() {
  const { activeSession, currentValues, disconnectLive } = useSimulationStore()

  // Belt-and-braces cleanup: `resetSession()`/mode switches already call
  // `disconnectLive()` themselves, but navigating away from Simulation Lab
  // entirely unmounts this component without going through either path —
  // the live stream must never keep running after the officer leaves the
  // page (task's own resource-safety requirement).
  useEffect(() => {
    return () => disconnectLive()
  }, [disconnectLive])

  if (!activeSession || currentValues === null) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="card flex flex-wrap items-center justify-between gap-2 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-ink-800">{activeSession.scenario_name}</p>
          <p className="text-xs text-ink-500">
            {activeSession.village_name} · {activeSession.status_display}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ModeIndicator />
          <SyntheticBadge />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[300px_minmax(0,1fr)_320px]">
        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Simulation controls"
        >
          <SimulationControlPanel />
        </aside>

        <main
          className="card min-w-0 max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Simulation intelligence"
        >
          <div className="space-y-4">
            <CurrentWeekSignalSummary />
            <AgentPipelineViewSection />
            <IntelligenceViewSection />
            <WhatIfResultView />
            <CounterfactualInvestigationSection />
          </div>
        </main>

        <aside
          className="card max-h-[calc(100vh-15rem)] min-h-[360px] overflow-y-auto p-4"
          aria-label="Alert intelligence"
        >
          <SimulationAlertPanel />
        </aside>
      </div>

      <SimulationBottomBar />
    </div>
  )
}

/** Thin wrapper so `AgentPipelineView` (unchanged) sits in the center
 *  viewport's own vertical rhythm without needing its own callers to know
 *  its prop shape. */
function AgentPipelineViewSection() {
  const { agentRuns, pipelineError } = useSimulationStore()
  return (
    <div className="border-t border-ink-200 pt-3 first:border-t-0 first:pt-0">
      <AgentPipelineView agentRuns={agentRuns} pipelineError={pipelineError} />
    </div>
  )
}

/** Thin wrapper resolving live-vs-replay intelligence for `IntelligenceView`
 *  (unchanged internally) — identical to how it was invoked before this
 *  layout change, just relocated into the center viewport. */
function IntelligenceViewSection() {
  const { replayWeek, replayIntelligence } = useSimulationStore()
  return (
    <div className="border-t border-ink-200 pt-3">
      <IntelligenceView
        override={replayWeek !== null ? replayIntelligence : undefined}
        viewingReplay={replayWeek !== null}
      />
    </div>
  )
}

export default function SimulationLabPage() {
  const { data, loading, error, reload } = useAsync<SimulationScenario[]>(() =>
    api.get('/simulation/scenarios/'),
  )
  const { activeSession, setScenarios } = useSimulationStore()

  useEffect(() => {
    if (data) setScenarios(data)
  }, [data, setScenarios])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Simulation Lab</h1>
          {!activeSession && (
            <p className="mt-0.5 text-sm text-ink-600">
              GramSentinel Intelligence Simulator — synthetic demonstration scenarios. Does
              not touch any real operational data.
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ScenarioSelector />
          {activeSession && <VillageScopeIndicator />}
        </div>
      </div>

      {!activeSession && <CurrentScopeBanner />}

      {activeSession ? (
        <SessionRunnerPanel />
      ) : loading && !data ? (
        <Loading label="Loading simulation scenarios…" />
      ) : error && !data ? (
        <ErrorNote message={error} onRetry={reload} />
      ) : (
        <Empty>Select a scenario above to begin.</Empty>
      )}
    </div>
  )
}

/**
 * Compact "Village A" scope indicator for the workspace header — the SAME
 * read-only `useAuth().user.village_name` source `CurrentScopeBanner`
 * already uses (never a second village state, never a selector). Shown
 * once a session is active, when the full `CurrentScopeBanner` card would
 * cost vertical space the command-center layout is specifically trying to
 * reclaim; `CurrentScopeBanner` itself is unchanged and still used as-is
 * on the scenario-picker screen.
 */
function VillageScopeIndicator() {
  const user = useAuth((state) => state.user)
  return (
    <span className="pill bg-sentinel-100 text-sentinel-700">
      {user?.village_name ?? 'No village assigned'}
    </span>
  )
}
