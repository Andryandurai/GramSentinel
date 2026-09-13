"""Phase 8 — the one simulation WebSocket consumer.

`SimulationSessionConsumer` is deliberately thin: authorize, join a
session-specific broadcast group, and translate a small set of client
control messages ("start"/"pause"/"resume"/"stop") into calls on
`simulation.live_runner.LiveSessionRunner`. It never computes a trend, a
safety verdict, or an intelligence payload itself — see `live_runner.py`'s
own docstring for exactly what does, and how it reuses the existing Phase
3/4/6 services unmodified.

Authorization mirrors the REST endpoints exactly (never a looser or
stricter rule than `simulation.permissions.SessionBelongsToOfficerVillage` +
`simulation.services.officer_may_access_village` already enforce for
`.../advance/` and friends):

  1. `scope["user"]` must be authenticated (set by `simulation.ws_auth.
     JWTAuthMiddleware` from a `?token=` query parameter — see that
     module's docstring for why a WebSocket needs a different auth
     transport than the REST API's `Authorization` header).
  2. The session id in the URL must exist.
  3. The session must be a REAL, officer-owned run (`health_officer_id` is
     not null) — never a seed-created template session (`models.
     get_template_session`'s own rows), which holds no per-officer state to
     stream.
  4. The user's role must be Health Officer or platform admin (same
     `IsHealthOfficer` rule the REST views apply).
  5. The user's own village (`users.scoping.scoped_village_id`) must match
     the session's village — `officer_may_access_village`, the exact same
     function `SimulationEngine.advance()` itself re-checks a second time
     server-side. A district-wide officer (no village) is unrestricted,
     same as everywhere else in this codebase.

Any failure above closes the socket with a specific 4xxx code *before*
`accept()` — never a silent drop, never merely hidden by the frontend UI.
"""

from __future__ import annotations

import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from users.models import User
from users.scoping import scoped_village_id

from .live_runner import LiveSessionRunner, SessionAlreadyRunning, get_active_runner
from .models import SimulationSession
from .services import officer_may_access_village


def _group_name(session_id: int) -> str:
    """Session-specific Channels group — never a global simulation group
    (task's own explicit requirement): every subscriber to this group has
    already been individually authorized for this exact session in
    `connect()` below, so a broadcast to it can never cross a village or
    session boundary by construction."""

    return f"simulation_session_{session_id}"


@database_sync_to_async
def _load_authorized_session(session_id: int, user) -> tuple[SimulationSession | None, str | None]:
    """Returns `(session, None)` on success or `(None, error_code)` on a
    specific, named failure — never a bare `None`/`None` the caller would
    have to guess about. `error_code` values map 1:1 to the WebSocket close
    codes `connect()` uses below."""

    if user is None or not getattr(user, "is_authenticated", False):
        return None, "unauthenticated"

    try:
        session = SimulationSession.objects.select_related("scenario", "village").get(pk=session_id)
    except SimulationSession.DoesNotExist:
        return None, "not_found"

    if session.health_officer_id is None:
        # A seed-created template session — not a real run, nothing to
        # stream. Treated as "not found" rather than "forbidden": it is not
        # a cross-village access attempt, it is simply not a live session.
        return None, "not_found"

    if getattr(user, "role", None) != User.Role.HEALTH_OFFICER and not getattr(
        user, "is_platform_admin", False
    ):
        return None, "forbidden"

    if not officer_may_access_village(session.village_id, user):
        return None, "forbidden"

    return session, None


_CLOSE_CODES = {
    "unauthenticated": 4401,
    "forbidden": 4403,
    "not_found": 4404,
}


class SimulationSessionConsumer(AsyncJsonWebsocketConsumer):
    @classmethod
    async def encode_json(cls, content):
        """`_serialize_agent_run`'s `started_at`/`ended_at` are real
        `datetime` objects — DRF's `JSONRenderer` serializes those
        automatically for the REST endpoints, but Channels' default
        `encode_json` is plain `json.dumps` and does not. Using Django's own
        `DjangoJSONEncoder` (the same encoder Django's admin/session/cache
        machinery already relies on) keeps this consumer's payloads byte-
        identical in spirit to what `.../advance/` already returns, without
        hand-rolling a second datetime-formatting convention."""

        import json

        from django.core.serializers.json import DjangoJSONEncoder

        return json.dumps(content, cls=DjangoJSONEncoder)

    async def connect(self):
        session_id = self.scope["url_route"]["kwargs"]["session_id"]
        user = self.scope.get("user")

        session, error = await _load_authorized_session(session_id, user)
        if error is not None:
            await self.close(code=_CLOSE_CODES[error])
            return

        self.session_id = session_id
        self.session_village_id = session.village_id
        self.officer = user
        self.group_name = _group_name(session_id)
        self._run_task = None

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        runner = get_active_runner(session_id)
        await self.send_json(
            {
                "type": "simulation.connected",
                "session_id": session.id,
                "village_id": session.village_id,
                "status": session.status,
                "week": session.replay_position,
                "is_complete": session.status == SimulationSession.Status.COMPLETED,
                "live_running": runner is not None,
                "live_paused": runner.is_paused if runner is not None else False,
            }
        )

    async def disconnect(self, code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            try:
                await self.channel_layer.group_discard(group_name, self.channel_name)
            except Exception:  # noqa: BLE001 - disconnect must never raise
                pass

        # Stop-on-close: a live run belongs to the connection that started
        # it. If this connection owns the active task, stop it — the
        # simulation must never keep executing after the officer closes the
        # page. An observer tab (one that never called "start") has no
        # `_run_task` and this is a no-op, leaving any other tab's run
        # untouched.
        run_task = getattr(self, "_run_task", None)
        if run_task is not None and not run_task.done():
            runner = get_active_runner(getattr(self, "session_id", None))
            if runner is not None:
                runner.stop()
            run_task.cancel()

    async def receive_json(self, content, **kwargs):
        action = content.get("action")
        if action == "start":
            await self._handle_start()
        elif action in ("pause", "resume", "stop"):
            await self._control(action)
        else:
            await self.send_json(
                {"type": "simulation.error", "session_id": self.session_id, "error": f"Unknown action: {action!r}"}
            )

    async def _handle_start(self):
        if get_active_runner(self.session_id) is not None:
            await self.send_json(
                {
                    "type": "simulation.error",
                    "session_id": self.session_id,
                    "error": "This session already has an active live run.",
                }
            )
            return

        runner = LiveSessionRunner(
            session_id=self.session_id, channel_layer=self.channel_layer, group_name=self.group_name
        )
        session = await _refresh_session(self.session_id)

        async def _drive():
            try:
                await runner.run(session=session, officer=self.officer)
            except SessionAlreadyRunning:
                pass

        self._run_task = asyncio.create_task(_drive())

    async def _control(self, action: str) -> None:
        runner = get_active_runner(self.session_id)
        if runner is None:
            await self.send_json(
                {
                    "type": "simulation.error",
                    "session_id": self.session_id,
                    "error": "No active live run to control.",
                }
            )
            return
        getattr(runner, action)()
        # "stop" is announced by the run loop itself once it actually
        # unwinds (it may be mid-stage) — but "pause"/"resume" have no
        # other checkpoint that would tell a connected tab the request was
        # received, so this consumer confirms them immediately. The run
        # loop's OWN state (`_pause_event`) is still the single source of
        # truth for whether progression is actually paused; this is only
        # ever a notification of that state, never a second copy of it.
        if action == "pause":
            await runner._broadcast("simulation.paused", {"week": None})
        elif action == "resume":
            await runner._broadcast("simulation.resumed", {"week": None})

    # -- Channels group event handler ---------------------------------
    # `LiveSessionRunner._broadcast` always sends one envelope type,
    # "simulation.broadcast" (-> this method, by Channels' dot->underscore
    # dispatch convention), carrying the real event under "event" — so
    # every actual event type (simulation.stage, simulation.week_started,
    # ...) is just JSON this consumer forwards verbatim, never a second
    # place that has to know every event type by name.
    async def simulation_broadcast(self, event):
        await self.send_json(event["event"])


@database_sync_to_async
def _refresh_session(session_id: int) -> SimulationSession:
    return SimulationSession.objects.select_related("scenario", "village").get(pk=session_id)
