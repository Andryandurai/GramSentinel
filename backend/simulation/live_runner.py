"""Phase 8 — Live Simulation Runner.

Streams a session's remaining weeks, one at a time, over an already-
authorized `SimulationSessionConsumer`'s channel layer group. This is NOT a
second simulation engine, a second orchestrator, or a second Safety Engine:
every week is advanced by the exact same `simulation.services.
SimulationEngine.advance()` the REST `.../sessions/<id>/advance/` endpoint
(Phase 3) already calls, which itself runs the exact same
`simulation.orchestrator.MultiAgentOrchestrator.run_pipeline()` (Phase 4)
and `simulation.safety.SafetyEngine` (Phase 6) — completely unmodified.

What this module adds is exactly two things:

  1. Observation. `advance()`/`_persist_agent_runs()`/`run_pipeline()` all
     gained optional `on_stage_start`/`on_stage_persisted` hooks (default
     `None` everywhere else, so every existing caller — the REST advance
     view, `WhatIfEngine` — is byte-for-byte unaffected). This module is the
     one caller that supplies them, to build a WebSocket event the instant
     each stage's `SimulationAgentRun` row is actually committed. Broadcast
     only ever happens after persistence — never before, never instead of.

  2. Pacing. `STAGE_PACING_SECONDS`/`WEEK_PACING_SECONDS` below are the
     ONLY simulation-pacing values in this whole feature, isolated here on
     purpose: they control how long the stream visually lingers between
     already-computed, already-persisted events before sending the next
     one. Setting either to 0 changes nothing about what is computed,
     classified, or stored — only how fast an officer sees it arrive. No
     other module in `simulation/` has, or needs, a pacing concept.

Persistence-before-broadcast: a whole week's `advance()` call (its own
`transaction.atomic()`) fully commits before this module sends a single
event for that week — see `_advance_one_week_sync`, which only collects
plain-dict event payloads into a list; nothing is sent over the wire from
inside that synchronous, `database_sync_to_async`-wrapped call. `run()`
drains that list afterwards, pacing included. The WebSocket stream is a
transport layer over already-true state; it is never itself the source of
truth (`SimulationAgentRun`/`SimulationSafetyCheck`/`SimulationResult` are,
exactly as they already were before Phase 8).

Concurrency: one `LiveSessionRunner` may be active per session at a time,
enforced by the process-local `_RUNNERS` registry below. An in-memory guard
is consistent with this project's existing single-process real-time
assumption (see `CHANNEL_LAYERS` in `config/settings.py`: "an in-memory
layer is enough for a single demo process"); a horizontally-scaled
deployment would need a database- or Redis-backed lock instead (documented
as a known limitation, not solved here).

Ownership: a live run belongs to the WebSocket connection that started it.
If that connection closes, `SimulationSessionConsumer.disconnect()` stops
the runner — the run must never keep executing after the officer closes the
page. Any other tab still connected to the same session's group merely
observes; closing an *observer* tab does not stop anything, and any
authorized tab can issue "start" again afterwards to resume driving from
the next unadvanced week (nothing is lost — every already-advanced week's
rows are already durably persisted).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from channels.db import database_sync_to_async

from .models import SimulationAgentRun, SimulationSession
from .services import (
    SimulationEngine,
    SimulationSessionNotRunning,
    SimulationVillageMismatch,
    _serialize_agent_run,
)

logger = logging.getLogger("gramsentinel.simulation")

#: Simulation pacing only — see module docstring. Neither value is read by
#: anything under `orchestrator.py`, `services.py`, or `safety/`; the
#: deterministic pipeline has no notion of these delays.
STAGE_PACING_SECONDS = 0.5
WEEK_PACING_SECONDS = 0.8

#: session_id -> the LiveSessionRunner currently driving it, this process
#: only. Presence in this dict is the one-authoritative-progression guard.
_RUNNERS: dict[int, "LiveSessionRunner"] = {}


class SessionAlreadyRunning(Exception):
    """A second 'start' was attempted for a session that already has an
    active live runner in this process."""


def get_active_runner(session_id: int) -> "LiveSessionRunner | None":
    return _RUNNERS.get(session_id)


class LiveSessionRunner:
    def __init__(self, *, session_id: int, channel_layer, group_name: str):
        self.session_id = session_id
        self.channel_layer = channel_layer
        self.group_name = group_name
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # not paused by default
        self._stop_requested = False

    # -- control, callable from any connected tab's consumer -------------
    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_requested = True
        self._pause_event.set()  # unblock a paused wait so stop takes effect

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    # -- broadcast ---------------------------------------------------------
    async def _broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "simulation.broadcast",
                "event": {"type": event_type, "session_id": self.session_id, **payload},
            },
        )

    # -- one week, entirely synchronous (Django ORM) ------------------------
    @staticmethod
    def _advance_one_week_sync(
        session: SimulationSession, officer, target_week: int, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Runs inside `database_sync_to_async` — no event loop is available
        in this thread, so it only ever appends plain-dict event payloads to
        `events`; `run()` sends them afterwards. `target_week` is captured
        by the caller *before* `advance()` runs (rather than read back off
        `session.replay_position` from inside a hook) so event payloads are
        correct regardless of exactly when `advance()` mutates that field.
        """

        def on_stage_start(agent_name: str) -> None:
            events.append(
                {
                    "type": "simulation.stage",
                    "week": target_week,
                    "stage": agent_name,
                    "status": SimulationAgentRun.Status.PROCESSING,
                }
            )

        def on_stage_persisted(run: SimulationAgentRun) -> None:
            events.append(
                {
                    "type": "simulation.stage",
                    "week": target_week,
                    "stage": run.agent_name,
                    "status": run.status,
                    "payload": _serialize_agent_run(run),
                }
            )

        return SimulationEngine.advance(
            session,
            officer,
            on_stage_start=on_stage_start,
            on_stage_persisted=on_stage_persisted,
        )

    # -- the run loop --------------------------------------------------------
    async def run(self, *, session: SimulationSession, officer) -> None:
        if self.session_id in _RUNNERS:
            raise SessionAlreadyRunning(self.session_id)
        _RUNNERS[self.session_id] = self
        try:
            await self._broadcast("simulation.started", {"village_id": session.village_id})
            while True:
                await self._pause_event.wait()
                if self._stop_requested:
                    await self._broadcast("simulation.stopped", {"week": session.replay_position})
                    return

                target_week = session.replay_position + 1
                events: list[dict[str, Any]] = []
                await self._broadcast("simulation.week_started", {"week": target_week})

                try:
                    state = await database_sync_to_async(self._advance_one_week_sync)(
                        session, officer, target_week, events
                    )
                except SimulationSessionNotRunning:
                    # Nothing left to advance — natural completion, not an
                    # error. Never present this as a fresh "outbreak" event;
                    # it is simply "no more seeded weeks".
                    await self._broadcast("simulation.completed", {"week": session.replay_position})
                    return
                except SimulationVillageMismatch:
                    await self._broadcast(
                        "simulation.error", {"error": "Village authorization failed for this session."}
                    )
                    return
                except Exception:  # noqa: BLE001 - a bug here must never crash the socket loop
                    logger.exception(
                        "[SIMULATION LIVE] advance() failed unexpectedly for session %s", self.session_id
                    )
                    await self._broadcast(
                        "simulation.error", {"error": "This reporting week could not be processed."}
                    )
                    return

                for event in events:
                    await self._pause_event.wait()
                    if self._stop_requested:
                        await self._broadcast("simulation.stopped", {"week": session.replay_position})
                        return
                    event_type = event.pop("type")
                    await self._broadcast(event_type, event)
                    if STAGE_PACING_SECONDS:
                        await asyncio.sleep(STAGE_PACING_SECONDS)

                await self._broadcast(
                    "simulation.week_completed", {"week": state["week"], "is_complete": state["is_complete"]}
                )

                if state["is_complete"]:
                    await self._broadcast("simulation.completed", {"week": state["week"]})
                    return

                if WEEK_PACING_SECONDS:
                    await asyncio.sleep(WEEK_PACING_SECONDS)
        finally:
            _RUNNERS.pop(self.session_id, None)
