import { create } from 'zustand'

import { api, buildSimulationSocketUrl, tokens, BASE_URL } from '@/services/api'
import type {
  FeedbackEvidenceSufficiency,
  FeedbackUsefulness,
  FeedbackYesNo,
  FeedbackYesPartiallyNo,
  InvestigationDecisionValue,
  SimulationAgentName,
  SimulationAgentRun,
  SimulationFeedbackState,
  SimulationIntelligence,
  SimulationInvestigationState,
  SimulationLiveEvent,
  SimulationLiveStageStatus,
  SimulationLiveStatus,
  SimulationReplaySpeed,
  SimulationReplayState,
  SimulationScenario,
  SimulationSessionState,
  SimulationWhatIfResult,
} from '@/types'

/**
 * Simulation Lab client state.
 *
 * `availableScenarios` is filled from the API response by the page (via the
 * existing `useAsync` loading/error pattern, same as every other page in
 * the app — see the Phase 1 audit's frontend-state-management finding).
 * `selectedScenario` is pure click-to-highlight UI state.
 *
 * `activeSession`/`currentWeek`/`currentValues`/`sessionStatus` hold exactly
 * what the backend last returned from `POST /simulation/sessions/` or
 * `POST /simulation/sessions/<id>/advance/` — nothing here is computed
 * locally. `startSession`/`advanceSession` call those endpoints directly
 * and replace this state wholesale with the response; there is no local
 * week counter and no client-generated synthetic value anywhere in this
 * store (Phase 3 task §10/§11/§18).
 *
 * `agentRuns` (Phase 4) is the same idea applied to the pipeline: it is
 * always exactly `activeSession.agent_runs` from the last response — empty
 * after `start()` (week 1 has no pipeline run yet), 5 entries after every
 * `advance()`. `pipelineLoading`/`pipelineError` piggyback on the same
 * `loading`/`error` flags `advanceSession` already sets, exposed under
 * their own names so the pipeline view can read intent-specific state
 * without implying scenario-list loading affects it.
 *
 * `intelligence` (Phase 5) is the ONE object every Signal Timeline /
 * Evidence Constellation / Source Fusion / Data Quality / "Why am I seeing
 * this?" component reads from — never five independent fetches (task
 * §20). It is loaded here, inside `startSession`/`advanceSession`
 * themselves, right after the session state those calls already fetched —
 * exactly the chain the Phase 5 task describes ("advance() -> agent_runs
 * returned -> fetch intelligence -> store intelligence -> render"). A
 * failed intelligence fetch is recorded in `intelligenceError` without
 * throwing — it must never break session start/advance, which already
 * succeeded by the time intelligence is requested.
 *
 * Phase 7 adds two independent feature areas (task §36 — never combine
 * them into one ambiguous mode):
 *
 * REPLAY ("what already happened?") — `replayWeek` is the week currently
 * being *viewed* via Previous/Next/a timeline click; `null` means "viewing
 * the live/current week", in which case components should read the
 * existing `intelligence` above rather than `replayIntelligence`. Only
 * navigating to a DIFFERENT week triggers a `GET .../replay/?week=N` call
 * — no redundant fetch for the week the store already has. Play/speed are
 * pure frontend presentation timing (task §10/§35): `replayPlaying`
 * toggles on/off and a component-level interval (not a store-level timer)
 * calls `stepReplay` on it; nothing here is a backend job.
 *
 * WHAT-IF ("what would happen if...?") — `whatIfResult` is the ONE object
 * every What-If comparison component reads from (original vs
 * hypothetical vs pipeline vs safety), populated by a single
 * `POST .../what-if/` call. The override *form inputs themselves* are
 * deliberately NOT stored here — they are plain component-local state
 * (an editable draft), since nothing outside the What-If panel needs them
 * and the backend is the only authority on the actual computed result.
 *
 * Phase 8 adds LIVE STREAMING ("watch the next weeks advance in real
 * time, one stage at a time, over a WebSocket") as a third independent
 * feature area, never mixed with Replay or What-If (only one of Live /
 * Replay / What-If is ever "the current mode" the officer is looking at).
 * Its own state is every field prefixed `live*` below, plus the module-
 * level `liveSocket` (a raw `WebSocket` — an imperative resource, not
 * reactive data, so it deliberately lives outside the store itself,
 * exactly like `replayPlaying`'s interval timer lives in a component
 * rather than in this file).
 *
 * Critically, Live Streaming does NOT duplicate `agentRuns`/`intelligence`/
 * `currentWeek`/`sessionStatus` — every `simulation.stage`/`week_completed`/
 * `completed` event updates those SAME existing fields in place (a stage's
 * `payload` IS a `SimulationAgentRun`, byte-identical in shape to what
 * `advanceSession()` already stores there; `week_completed` triggers the
 * same read-only `loadIntelligence()` `advanceSession()` already calls).
 * `AgentPipelineView`/`IntelligenceView`/`SimulationAlertPanel` therefore
 * need no Phase 8 changes at all — they simply keep reading `agentRuns`/
 * `intelligence` and start reflecting live progress automatically. The
 * `live*` fields exist only for what genuinely has no existing
 * counterpart: connection health, which stage is *currently* PROCESSING
 * before its row exists to put in `agentRuns`, and pause/run state.
 */
interface SimulationState {
  availableScenarios: SimulationScenario[]
  selectedScenario: SimulationScenario | null
  sessionId: number | null
  activeSession: SimulationSessionState | null
  currentWeek: number | null
  currentValues: SimulationSessionState['values'] | null
  sessionStatus: string | null
  agentRuns: SimulationAgentRun[]
  pipelineLoading: boolean
  pipelineError: string | null
  intelligence: SimulationIntelligence | null
  intelligenceLoading: boolean
  intelligenceError: string | null
  loading: boolean
  error: string | null

  // Phase 7 — Replay
  replayWeek: number | null
  replayIntelligence: SimulationIntelligence | null
  replayLoading: boolean
  replayError: string | null
  replayPlaying: boolean
  replaySpeed: SimulationReplaySpeed

  // Phase 7 — What-If
  whatIfLoading: boolean
  whatIfError: string | null
  whatIfResult: SimulationWhatIfResult | null

  // Counterfactual Investigation — Village A only, a structured UI over the
  // exact same What-If pipeline/response shape (see `runCounterfactual`).
  counterfactualLoading: boolean
  counterfactualError: string | null
  counterfactualResult: SimulationWhatIfResult | null

  // Phase 8 — Live Streaming
  liveStatus: SimulationLiveStatus
  liveRunning: boolean
  livePaused: boolean
  liveWeek: number | null
  liveStage: SimulationAgentName | null
  liveStageStatuses: Partial<Record<SimulationAgentName, SimulationLiveStageStatus>>
  liveError: string | null
  liveEvents: SimulationLiveEvent[]

  // Phase 9 — Investigation Notebook
  investigation: SimulationInvestigationState | null
  investigationLoading: boolean
  investigationError: string | null
  investigationSaving: boolean
  investigationDecisionSaving: boolean
  investigationReportLoading: boolean
  investigationSection: string

  // Phase 10 — Feedback
  feedback: SimulationFeedbackState | null
  feedbackLoading: boolean
  feedbackSaving: boolean
  feedbackError: string | null

  setScenarios: (scenarios: SimulationScenario[]) => void
  selectScenario: (scenario: SimulationScenario | null) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  startSession: (scenarioId: number) => Promise<void>
  advanceSession: () => Promise<void>
  resetSession: () => void

  stepReplay: (week: number) => Promise<void>
  exitReplay: () => void
  setReplayPlaying: (playing: boolean) => void
  setReplaySpeed: (speed: SimulationReplaySpeed) => void

  runWhatIf: (overrides: Record<string, number | null>) => Promise<void>
  resetWhatIf: () => void

  runCounterfactual: (overrides: Record<string, number | null>) => Promise<void>
  resetCounterfactual: () => void

  connectLive: () => void
  disconnectLive: () => void
  startLive: () => void
  pauseLive: () => void
  resumeLive: () => void
  stopLive: () => void

  setInvestigationSection: (section: string) => void
  loadInvestigation: (sessionId: number) => Promise<void>
  saveInvestigationNotes: (notes: string) => void
  updateInvestigationChecklist: (patch: Record<string, boolean>) => Promise<void>
  addInvestigationObservation: (input: {
    week: number
    source: string
    category?: string
    notes: string
  }) => Promise<void>
  recordInvestigationDecision: (decision: InvestigationDecisionValue, reason?: string) => Promise<void>
  exportInvestigationReport: () => Promise<void>
  resetInvestigation: () => void

  loadFeedback: (sessionId: number) => Promise<void>
  saveFeedback: (patch: {
    usefulness?: FeedbackUsefulness
    evidence_sufficiency?: FeedbackEvidenceSufficiency
    recommendation_helpful?: FeedbackYesPartiallyNo
    additional_verification_required?: FeedbackYesNo
    comment?: string
  }) => Promise<void>
}

function applySessionState(
  set: (partial: Partial<SimulationState>) => void,
  state: SimulationSessionState,
) {
  set({
    activeSession: state,
    sessionId: state.session_id,
    currentWeek: state.week,
    currentValues: state.values,
    sessionStatus: state.status,
    agentRuns: state.agent_runs,
    loading: false,
    error: null,
    pipelineLoading: false,
    pipelineError: null,
  })
}

/** The single Phase 5 fetch — called once, from inside the store, right
 * after `startSession`/`advanceSession` already applied the new session
 * state. Never called independently by a component, and never called more
 * than once per session-state change (task §20/§33). */
async function loadIntelligence(
  set: (partial: Partial<SimulationState>) => void,
  sessionId: number,
) {
  set({ intelligenceLoading: true, intelligenceError: null })
  try {
    const intelligence = await api.get<SimulationIntelligence>(
      `/simulation/sessions/${sessionId}/intelligence/`,
    )
    set({ intelligence, intelligenceLoading: false, intelligenceError: null })
  } catch (error) {
    set({
      intelligenceLoading: false,
      intelligenceError:
        error instanceof Error
          ? error.message
          : 'Unable to load signal intelligence for this session.',
    })
  }
}

// ---------------------------------------------------------------------------
// Phase 8 — Live Streaming WebSocket client.
//
// Module-level, not store state, on purpose (see the file-header comment):
// a `WebSocket` instance and its reconnect timer are imperative resources,
// not data a component should re-render on. Exactly one socket exists at a
// time — `connectLive()` is a no-op if one is already open/connecting, so a
// component re-mounting (e.g. React StrictMode, or switching tabs and back)
// can never create a duplicate subscription (task's own "no duplicate
// WebSocket connections" requirement).
// ---------------------------------------------------------------------------
type SetState = (
  partial:
    | Partial<SimulationState>
    | ((state: SimulationState) => Partial<SimulationState>),
) => void
type GetState = () => SimulationState

let liveSocket: WebSocket | null = null
let liveReconnectTimer: ReturnType<typeof setTimeout> | null = null
let liveReconnectAttempts = 0
let liveWantedConnected = false

const LIVE_MAX_EVENTS = 50
const LIVE_RECONNECT_MAX_DELAY_MS = 10_000

// ---------------------------------------------------------------------------
// Phase 9 — Investigation notes autosave debounce (task §17: "debounce
// requests, do not create a row for every keystroke"). A single module-
// level timer, exactly like the live-socket reconnect timer above — never
// more than one pending save at a time.
// ---------------------------------------------------------------------------
let notesDebounceTimer: ReturnType<typeof setTimeout> | null = null
const NOTES_DEBOUNCE_MS = 800

function clearNotesDebounceTimer() {
  if (notesDebounceTimer) {
    clearTimeout(notesDebounceTimer)
    notesDebounceTimer = null
  }
}

function clearLiveReconnectTimer() {
  if (liveReconnectTimer) {
    clearTimeout(liveReconnectTimer)
    liveReconnectTimer = null
  }
}

function handleLiveEvent(event: SimulationLiveEvent, set: SetState, get: GetState) {
  set((state) => ({ liveEvents: [...state.liveEvents, event].slice(-LIVE_MAX_EVENTS) }))

  switch (event.type) {
    case 'simulation.connected':
      set({
        liveRunning: Boolean(event.live_running),
        livePaused: Boolean(event.live_paused),
        liveWeek: event.week ?? null,
      })
      break

    case 'simulation.started':
      set({ liveRunning: true, livePaused: false, liveError: null })
      break

    case 'simulation.week_started':
      // A fresh week's stages start WAITING, exactly like a brand-new
      // `start()` response — never carry the previous week's COMPLETE
      // cards over visually.
      set({ liveWeek: event.week ?? null, liveStage: null, liveStageStatuses: {}, agentRuns: [] })
      break

    case 'simulation.stage': {
      const stage = event.stage
      if (!stage) break
      set((state) => ({
        liveStage: event.status === 'PROCESSING' ? stage : state.liveStage,
        liveStageStatuses: {
          ...state.liveStageStatuses,
          [stage]: event.status ?? state.liveStageStatuses[stage],
        },
      }))
      // `event.payload` is a `SimulationAgentRun`, persisted the instant
      // this event was sent — the exact same shape `agentRuns` already
      // holds after `advanceSession()`. Upserting it here is what lets
      // `AgentPipelineView` show live progress with no changes of its own.
      if (event.payload && (event.status === 'COMPLETE' || event.status === 'FAILED')) {
        const payload = event.payload
        set((state) => ({
          agentRuns: [...state.agentRuns.filter((run) => run.agent_name !== stage), payload],
        }))
      }
      break
    }

    case 'simulation.week_completed': {
      set((state) => ({
        currentWeek: event.week ?? state.currentWeek,
        activeSession: state.activeSession
          ? { ...state.activeSession, week: event.week ?? state.activeSession.week }
          : state.activeSession,
      }))
      const sessionId = get().sessionId
      if (sessionId) void loadIntelligence(set, sessionId)
      break
    }

    case 'simulation.completed':
      set((state) => ({
        liveRunning: false,
        livePaused: false,
        sessionStatus: 'COMPLETED',
        activeSession: state.activeSession
          ? { ...state.activeSession, status: 'COMPLETED', is_complete: true }
          : state.activeSession,
      }))
      break

    case 'simulation.paused':
      set({ livePaused: true })
      break

    case 'simulation.resumed':
      set({ livePaused: false })
      break

    case 'simulation.stopped':
      set({ liveRunning: false, livePaused: false })
      break

    case 'simulation.error':
      set({ liveError: event.error ?? 'A live simulation error occurred.' })
      break

    default:
      break
  }
}

function openLiveSocket(sessionId: number, set: SetState, get: GetState) {
  set({
    liveStatus: liveReconnectAttempts > 0 ? 'RECONNECTING' : 'CONNECTING',
    liveError: null,
  })

  const socket = new WebSocket(buildSimulationSocketUrl(sessionId))
  liveSocket = socket

  socket.onopen = () => {
    liveReconnectAttempts = 0
    set({ liveStatus: 'CONNECTED' })
  }

  socket.onmessage = (message) => {
    let parsed: SimulationLiveEvent
    try {
      parsed = JSON.parse(message.data)
    } catch {
      return
    }
    handleLiveEvent(parsed, set, get)
  }

  socket.onerror = () => {
    set({ liveStatus: 'ERROR', liveError: 'The live connection encountered an error.' })
  }

  socket.onclose = () => {
    liveSocket = null
    if (!liveWantedConnected) {
      set({ liveStatus: 'IDLE' })
      return
    }
    // Reconnect with capped exponential backoff — never a tight loop, and
    // never more than one pending timer (task's own "no infinite
    // reconnect loops" requirement).
    set({ liveStatus: 'RECONNECTING' })
    const delay = Math.min(1000 * 2 ** liveReconnectAttempts, LIVE_RECONNECT_MAX_DELAY_MS)
    liveReconnectAttempts += 1
    clearLiveReconnectTimer()
    liveReconnectTimer = setTimeout(() => {
      if (liveWantedConnected) openLiveSocket(sessionId, set, get)
    }, delay)
  }
}

export const useSimulationStore = create<SimulationState>((set, get) => ({
  availableScenarios: [],
  selectedScenario: null,
  sessionId: null,
  activeSession: null,
  currentWeek: null,
  currentValues: null,
  sessionStatus: null,
  agentRuns: [],
  pipelineLoading: false,
  pipelineError: null,
  intelligence: null,
  intelligenceLoading: false,
  intelligenceError: null,
  loading: false,
  error: null,

  replayWeek: null,
  replayIntelligence: null,
  replayLoading: false,
  replayError: null,
  replayPlaying: false,
  replaySpeed: 1,

  whatIfLoading: false,
  whatIfError: null,
  whatIfResult: null,

  counterfactualLoading: false,
  counterfactualError: null,
  counterfactualResult: null,

  liveStatus: 'IDLE',
  liveRunning: false,
  livePaused: false,
  liveWeek: null,
  liveStage: null,
  liveStageStatuses: {},
  liveError: null,
  liveEvents: [],

  investigation: null,
  investigationLoading: false,
  investigationError: null,
  investigationSaving: false,
  investigationDecisionSaving: false,
  investigationReportLoading: false,
  investigationSection: 'overview',

  feedback: null,
  feedbackLoading: false,
  feedbackSaving: false,
  feedbackError: null,

  setScenarios: (scenarios) => set({ availableScenarios: scenarios }),
  selectScenario: (scenario) => set({ selectedScenario: scenario }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),

  async startSession(scenarioId) {
    set({ loading: true, error: null })
    try {
      const state = await api.post<SimulationSessionState>('/simulation/sessions/', {
        scenario_id: scenarioId,
      })
      applySessionState(set, state)
      void loadIntelligence(set, state.session_id)
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Could not start the simulation.',
      })
      throw error
    }
  },

  async advanceSession() {
    const { activeSession } = get()
    if (!activeSession) return
    set({ loading: true, error: null, pipelineLoading: true, pipelineError: null })
    try {
      const state = await api.post<SimulationSessionState>(
        `/simulation/sessions/${activeSession.session_id}/advance/`,
      )
      applySessionState(set, state)
      void loadIntelligence(set, state.session_id)
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : 'Unable to advance the simulation. Please try again.'
      set({
        loading: false,
        error: message,
        pipelineLoading: false,
        pipelineError: message,
      })
      throw error
    }
  },

  resetSession: () => {
    get().disconnectLive()
    get().resetInvestigation()
    set({
      activeSession: null,
      sessionId: null,
      currentWeek: null,
      currentValues: null,
      sessionStatus: null,
      agentRuns: [],
      pipelineLoading: false,
      pipelineError: null,
      intelligence: null,
      intelligenceLoading: false,
      intelligenceError: null,
      error: null,
      replayWeek: null,
      replayIntelligence: null,
      replayLoading: false,
      replayError: null,
      replayPlaying: false,
      whatIfLoading: false,
      whatIfError: null,
      whatIfResult: null,
      counterfactualLoading: false,
      counterfactualError: null,
      counterfactualResult: null,
    })
  },

  async stepReplay(week) {
    const { activeSession } = get()
    if (!activeSession) return
    // Live and Replay are never mixed (task §26): opening Replay ends the
    // current live viewing session rather than leaving an ambiguous "which
    // one is real" state. The officer can start Live again afterwards.
    if (get().liveStatus !== 'IDLE') get().disconnectLive()
    set({ replayLoading: true, replayError: null })
    try {
      const state = await api.get<SimulationReplayState>(
        `/simulation/sessions/${activeSession.session_id}/replay/?week=${week}`,
      )
      set({
        replayWeek: state.week,
        replayIntelligence: state.intelligence,
        replayLoading: false,
        replayError: null,
        // Play auto-stops at the last computed week — never wraps or
        // silently restarts (task §10).
        replayPlaying: get().replayPlaying && !state.is_last,
      })
    } catch (error) {
      set({
        replayLoading: false,
        replayPlaying: false,
        replayError:
          error instanceof Error ? error.message : 'Unable to load that replay week.',
      })
    }
  },

  exitReplay: () =>
    set({ replayWeek: null, replayIntelligence: null, replayError: null, replayPlaying: false }),

  setReplayPlaying: (playing) => set({ replayPlaying: playing }),
  setReplaySpeed: (speed) => set({ replaySpeed: speed }),

  async runWhatIf(overrides) {
    const { activeSession } = get()
    if (!activeSession) return
    // Same isolation rule as Replay above — What-If must never be streamed
    // or shown as if it were live progression (task §27/§28).
    if (get().liveStatus !== 'IDLE') get().disconnectLive()
    set({ whatIfLoading: true, whatIfError: null })
    try {
      const result = await api.post<SimulationWhatIfResult>(
        `/simulation/sessions/${activeSession.session_id}/what-if/`,
        { overrides },
      )
      set({ whatIfResult: result, whatIfLoading: false, whatIfError: null })
    } catch (error) {
      set({
        whatIfLoading: false,
        whatIfError:
          error instanceof Error ? error.message : 'Unable to run this What-If scenario.',
      })
      throw error
    }
  },

  resetWhatIf: () => set({ whatIfResult: null, whatIfError: null, whatIfLoading: false }),

  async runCounterfactual(overrides) {
    const { activeSession } = get()
    if (!activeSession) return
    set({ counterfactualLoading: true, counterfactualError: null })
    try {
      const result = await api.post<SimulationWhatIfResult>(
        `/simulation/sessions/${activeSession.session_id}/counterfactual/`,
        { overrides },
      )
      set({ counterfactualResult: result, counterfactualLoading: false, counterfactualError: null })
    } catch (error) {
      set({
        counterfactualLoading: false,
        counterfactualError:
          error instanceof Error
            ? error.message
            : 'Unable to run this counterfactual investigation.',
      })
      throw error
    }
  },

  resetCounterfactual: () =>
    set({ counterfactualResult: null, counterfactualError: null, counterfactualLoading: false }),

  connectLive() {
    const sessionId = get().sessionId
    if (!sessionId) return
    liveWantedConnected = true
    if (liveSocket && (liveSocket.readyState === WebSocket.OPEN || liveSocket.readyState === WebSocket.CONNECTING)) {
      // Already connected/connecting for this component instance — never a
      // second, duplicate subscription (task's own multi-tab/remount rule).
      return
    }
    liveReconnectAttempts = 0
    openLiveSocket(sessionId, set, get)
  },

  disconnectLive() {
    liveWantedConnected = false
    clearLiveReconnectTimer()
    liveReconnectAttempts = 0
    if (liveSocket) {
      liveSocket.close()
      liveSocket = null
    }
    set({
      liveStatus: 'IDLE',
      liveRunning: false,
      livePaused: false,
      liveStage: null,
      liveStageStatuses: {},
      liveError: null,
    })
  },

  startLive: () => liveSocket?.send(JSON.stringify({ action: 'start' })),
  pauseLive: () => liveSocket?.send(JSON.stringify({ action: 'pause' })),
  resumeLive: () => liveSocket?.send(JSON.stringify({ action: 'resume' })),
  stopLive: () => liveSocket?.send(JSON.stringify({ action: 'stop' })),

  setInvestigationSection: (section) => set({ investigationSection: section }),

  async loadInvestigation(sessionId) {
    set({ investigationLoading: true, investigationError: null })
    try {
      const investigation = await api.get<SimulationInvestigationState>(
        `/simulation/sessions/${sessionId}/investigation/`,
      )
      set({ investigation, investigationLoading: false, investigationError: null })
    } catch (error) {
      set({
        investigationLoading: false,
        investigationError:
          error instanceof Error ? error.message : 'Unable to load the investigation.',
      })
    }
  },

  saveInvestigationNotes(notes) {
    const { activeSession, investigation } = get()
    if (!activeSession || !investigation) return
    // Optimistic local update — the officer keeps typing without waiting
    // on the network; the debounced call below is the only thing that
    // actually persists it (task §17).
    set({ investigation: { ...investigation, notes } })

    clearNotesDebounceTimer()
    notesDebounceTimer = setTimeout(() => {
      void (async () => {
        set({ investigationSaving: true })
        try {
          const updated = await api.patch<SimulationInvestigationState>(
            `/simulation/sessions/${activeSession.session_id}/investigation/`,
            { notes },
          )
          set({ investigation: updated, investigationSaving: false, investigationError: null })
        } catch (error) {
          set({
            investigationSaving: false,
            investigationError:
              error instanceof Error ? error.message : 'Unable to save investigation notes.',
          })
        }
      })()
    }, NOTES_DEBOUNCE_MS)
  },

  async updateInvestigationChecklist(patch) {
    const { activeSession } = get()
    if (!activeSession) return
    set({ investigationSaving: true })
    try {
      const updated = await api.patch<SimulationInvestigationState>(
        `/simulation/sessions/${activeSession.session_id}/investigation/`,
        { checklist: patch },
      )
      set({ investigation: updated, investigationSaving: false, investigationError: null })
    } catch (error) {
      set({
        investigationSaving: false,
        investigationError:
          error instanceof Error ? error.message : 'Unable to update the checklist.',
      })
      throw error
    }
  },

  async addInvestigationObservation(input) {
    const { activeSession } = get()
    if (!activeSession) return
    set({ investigationSaving: true })
    try {
      const updated = await api.post<SimulationInvestigationState>(
        `/simulation/sessions/${activeSession.session_id}/investigation/observations/`,
        input,
      )
      set({ investigation: updated, investigationSaving: false, investigationError: null })
    } catch (error) {
      set({
        investigationSaving: false,
        investigationError:
          error instanceof Error ? error.message : 'Unable to save the field observation.',
      })
      throw error
    }
  },

  async recordInvestigationDecision(decision, reason) {
    const { activeSession } = get()
    if (!activeSession) return
    set({ investigationDecisionSaving: true, investigationError: null })
    try {
      const updated = await api.post<SimulationInvestigationState>(
        `/simulation/sessions/${activeSession.session_id}/investigation/decision/`,
        { decision, reason },
      )
      set({ investigation: updated, investigationDecisionSaving: false, investigationError: null })
    } catch (error) {
      set({
        investigationDecisionSaving: false,
        investigationError:
          error instanceof Error ? error.message : 'Unable to record this decision.',
      })
      throw error
    }
  },

  async exportInvestigationReport() {
    const { activeSession } = get()
    if (!activeSession) return
    set({ investigationReportLoading: true, investigationError: null })
    try {
      const access = tokens.access()
      const response = await fetch(
        `${BASE_URL}/simulation/sessions/${activeSession.session_id}/investigation/report/`,
        { headers: access ? { Authorization: `Bearer ${access}` } : {} },
      )
      if (!response.ok) throw new Error('Unable to generate the investigation report.')
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `gramsentinel-investigation-session-${activeSession.session_id}.pdf`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      set({ investigationReportLoading: false })
    } catch (error) {
      set({
        investigationReportLoading: false,
        investigationError:
          error instanceof Error ? error.message : 'Unable to export the investigation report.',
      })
      throw error
    }
  },

  resetInvestigation: () => {
    clearNotesDebounceTimer()
    set({
      investigation: null,
      investigationLoading: false,
      investigationError: null,
      investigationSaving: false,
      investigationDecisionSaving: false,
      investigationReportLoading: false,
      investigationSection: 'overview',
      feedback: null,
      feedbackLoading: false,
      feedbackSaving: false,
      feedbackError: null,
    })
  },

  async loadFeedback(sessionId) {
    set({ feedbackLoading: true, feedbackError: null })
    try {
      const feedback = await api.get<SimulationFeedbackState>(
        `/simulation/sessions/${sessionId}/investigation/feedback/`,
      )
      set({ feedback, feedbackLoading: false, feedbackError: null })
    } catch (error) {
      set({
        feedbackLoading: false,
        feedbackError: error instanceof Error ? error.message : 'Unable to load feedback.',
      })
    }
  },

  async saveFeedback(patch) {
    const { activeSession } = get()
    if (!activeSession) return
    set({ feedbackSaving: true, feedbackError: null })
    try {
      const feedback = await api.patch<SimulationFeedbackState>(
        `/simulation/sessions/${activeSession.session_id}/investigation/feedback/`,
        patch,
      )
      set({ feedback, feedbackSaving: false, feedbackError: null })
    } catch (error) {
      set({
        feedbackSaving: false,
        feedbackError: error instanceof Error ? error.message : 'Unable to save feedback.',
      })
      throw error
    }
  },
}))
