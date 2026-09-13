# GramSentinel Intelligence Simulator — Phase 8: Live Emergence + Real-Time Streaming

Adds a Django Channels WebSocket layer around the existing, unmodified Phase
3/4/6 simulation pipeline so the Simulation Lab can stream a session's
remaining weeks stage-by-stage instead of the officer clicking "Next Week"
and waiting for one synchronous response. Still a **synthetic simulation**
only — never real surveillance, never a real outbreak declaration, never an
operational `Alert`/`CommunityReport`/notification.

## What this is not

- Not a second `MultiAgentOrchestrator`, `SafetyEngine`, Replay engine, or
  What-If engine. Every week is advanced by the exact same
  `simulation.services.SimulationEngine.advance()` the REST
  `.../advance/` endpoint already calls.
- Not a second intelligence representation. `simulation.stage` events carry
  the same `SimulationAgentRun` shape the REST API already returns; a
  completed week triggers the frontend's existing `GET .../intelligence/`
  read, never a WebSocket-only payload.
- Not a persistence layer of its own. `SimulationAgentRun`/
  `SimulationSafetyCheck`/`SimulationResult` remain the source of truth;
  WebSocket messages are transport events sent only after a row is already
  committed.

## Endpoint and authentication

`WS /ws/simulation/sessions/<session_id>/?token=<JWT access token>`

Browsers cannot set an `Authorization` header on a `WebSocket`, so the same
JWT the REST client already holds (`localStorage['gs.access']`) travels as
a query parameter instead. `simulation/ws_auth.py::JWTAuthMiddleware` wraps
only this route (`simulation/routing.py`) — it resolves `scope["user"]`
from that token and nothing else; it never itself decides who may connect.
The existing `alerts` WebSocket route and its `AuthMiddlewareStack`-based
session auth are untouched.

## Authorization (server-side, every connection)

`simulation/consumers.py::_load_authorized_session` runs on every `connect()`
and closes with a specific code before `accept()` if any check fails:

| Check | Failure code |
|---|---|
| `scope["user"]` is authenticated | `4401` |
| Session id exists | `4404` |
| Session is a real, officer-owned run (`health_officer_id` not null) — never the seed-created template | `4404` |
| Role is Health Officer or platform admin | `4403` |
| `officer_may_access_village(session.village_id, user)` — same function `SimulationEngine.advance()` re-checks server-side | `4403` |

A district-wide officer (no village) is unrestricted, matching every other
village-scoped check in this codebase. There is no village selector and no
Village C anywhere in this feature.

## Event contract

Every event is `{"type": ..., "session_id": ..., ...}`, broadcast to a
**session-specific** Channels group `simulation_session_<id>` — never a
global group, so a broadcast cannot cross a session or village boundary by
construction (every group member was individually authorized above).

| Type | Meaning |
|---|---|
| `simulation.connected` | Sent once, directly to the new connection only — a resync snapshot (`week`, `status`, `is_complete`, `live_running`, `live_paused`) |
| `simulation.started` | A live run began for this session |
| `simulation.week_started` | `{week}` — about to advance into this week |
| `simulation.stage` | `{week, stage, status: PROCESSING\|COMPLETE\|FAILED, payload?}` — `payload` is a full `SimulationAgentRun`, present only once the row is persisted |
| `simulation.week_completed` | `{week, is_complete}` |
| `simulation.completed` | The scenario has no more seeded weeks |
| `simulation.paused` / `simulation.resumed` | Acknowledges a `pause`/`resume` control message |
| `simulation.stopped` | The run ended (officer-requested, or connection closed) |
| `simulation.error` | `{error}` — a stage/week could not be processed, or a control message was invalid |

Stages always stream in the fixed order `ingestion → signal_analysis →
correlation → evidence → safety`, each as `PROCESSING` then `COMPLETE` or
`FAILED`. If a stage fails, every downstream stage (including `safety`)
streams as `FAILED` — never silently omitted, never falsely `COMPLETE`.

Client → server control messages: `{"action": "start" | "pause" | "resume" | "stop"}`.

## The live runner (`simulation/live_runner.py`)

`LiveSessionRunner.run()` loops: wait if paused → call
`SimulationEngine.advance()` (inside `database_sync_to_async`, with
`on_stage_start`/`on_stage_persisted` hooks — new optional keyword
arguments on `advance()`/`_persist_agent_runs()`/`run_pipeline()`, default
`None` everywhere, so no other caller's behaviour changed) → drain the
collected stage events with a pacing delay → repeat until the scenario
completes or the officer stops it.

**Persistence before broadcast, always.** `advance()`'s own
`transaction.atomic()` fully commits before a single event for that week is
sent — the collected events are plain dicts appended during the
synchronous call, then broadcast (with pacing) only after it returns.

**Pacing is cosmetic and isolated.** `STAGE_PACING_SECONDS` /
`WEEK_PACING_SECONDS` (both in `live_runner.py`) control only how long the
stream visually lingers between already-computed, already-persisted
results. Setting both to `0` changes nothing about what is computed or
stored — this is exercised directly by the test suite (`_fast_pacing`
fixture in `tests/test_simulation_live.py`).

**Concurrency.** `_RUNNERS: dict[session_id, LiveSessionRunner]` is a
process-local registry: one live run per session at a time. A second
`"start"` for an already-running session gets a `simulation.error`, not a
duplicate pipeline execution. This is an in-memory guard, consistent with
this project's existing single-process assumption for real-time features
(`CHANNEL_LAYERS` is `InMemoryChannelLayer` — see `config/settings.py`); a
horizontally-scaled deployment would need a database- or Redis-backed lock
instead (not implemented here — see Known Limitations in the Phase 8
final report).

**Ownership and cleanup.** A run belongs to the WebSocket connection that
started it. `disconnect()` stops it (`runner.stop()` then a cancellation
backstop) — the simulation never keeps executing after the officer closes
the page. Any other tab watching the same session is unaffected by its own
disconnect; it can issue its own `"start"` afterwards to resume driving
from the next unadvanced week (nothing is lost — every already-advanced
week is already durably persisted).

## Reconnection

The frontend (`frontend/src/store/simulation.ts`) reconnects with capped
exponential backoff (1s → 2s → 4s → … → 10s) while `liveWantedConnected` is
true, and stops immediately on an explicit `disconnectLive()`. A fresh
connection always re-authorizes from scratch and receives a new
`simulation.connected` snapshot — the smallest safe resync mechanism: no
event log replay, no attempt to reconstruct a gap. Live/Replay/What-If are
mutually exclusive in the store: entering Replay or What-If disconnects an
active Live stream first (`stepReplay`/`runWhatIf` in `simulation.ts`).

## Frontend state (`frontend/src/store/simulation.ts`)

Extended in place — no second store. New fields are all prefixed `live*`
(`liveStatus`, `liveRunning`, `livePaused`, `liveWeek`, `liveStage`,
`liveStageStatuses`, `liveError`, `liveEvents`). Everything else a
`simulation.stage`/`week_completed` event implies is written into the
**existing** fields: a stage's `payload` is upserted into `agentRuns`
(the same shape `advanceSession()` already populates, so `AgentPipelineView`
needs no changes), and `week_completed` triggers the existing read-only
`loadIntelligence()` call. `SimulationLab.tsx` reuses every existing panel
unchanged; Phase 8 only added a `LiveControls` section (left panel), a
`ModeIndicator` pill (LIVE / REPLAY / WHAT-IF, header), and a live variant
of the persistent bottom bar (`SimulationBottomBar`) shown only while
`liveStatus !== 'IDLE'` and Replay isn't being viewed.

## `LIVE_EMERGENCE` scenario

`SimulationScenario.ScenarioType.LIVE_EMERGENCE` existed as a schema-only
enum value since Phase 2. `core/management/commands/seed_demo.py` now seeds
one 5-week "Live Signal Emergence" scenario for Village A, using the exact
same fields and `update_or_create` idempotency as the other three seeded
scenarios — no new scenario model, no new scoring algorithm. Run
`python manage.py seed_demo` to pick it up in an existing dev database.

## Safety

Nothing under `simulation/safety/` was touched. The live path calls
`SafetyEngine.evaluate_latest()` exactly as `advance()` always has; a
malicious/degraded upstream narrative is still `BLOCK`ed and an LLM outage
still leaves the deterministic trend untouched — both verified end-to-end
over the WebSocket path in `tests/test_simulation_live.py` (section C).
