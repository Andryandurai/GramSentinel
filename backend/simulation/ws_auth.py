"""Phase 8 — WebSocket authentication for the simulation app.

The REST API authenticates exclusively via JWT bearer tokens
(`rest_framework_simplejwt`, `frontend/src/services/api.ts` keeps the access
token in `localStorage['gs.access']` and sends `Authorization: Bearer
<token>`). A browser `WebSocket` cannot set that header, so the token
travels as a `?token=` query-string parameter on the connection URL instead
— the one place it can go without a custom subprotocol negotiation. This is
the ONLY thing this middleware does: resolve `scope["user"]` from that
token, the same way `JWTAuthentication` resolves `request.user` for REST.

Deliberately NOT a replacement for `channels.auth.AuthMiddlewareStack`
(`config/asgi.py` still uses that, unmodified, for the existing
`alerts.consumers.OfficerAlertConsumer`): this middleware wraps only the
simulation WebSocket route (see `simulation/routing.py`), so it changes
authentication for that route alone and leaves every other consumer's
behaviour exactly as it was before Phase 8.

Authorization (which village/session/role a token's user may actually
access) is NOT decided here — that is `SimulationSessionConsumer.connect()`'s
job, mirroring the same `officer_may_access_village`/role checks the REST
views already apply. This module only ever answers "who is this?", never
"what may they do?".
"""

from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _user_from_token(token: str):
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    from django.contrib.auth import get_user_model

    try:
        validated = AccessToken(token)
        user_id = validated["user_id"]
    except (TokenError, KeyError):
        return AnonymousUser()

    try:
        return get_user_model().objects.get(pk=user_id, is_active=True)
    except get_user_model().DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware:
    """Wraps a single ASGI application (a consumer, or `URLRouter(...)` of
    several) and resolves `scope["user"]` from a `?token=` query parameter
    before delegating. Never raises on a missing/invalid token — it sets
    `AnonymousUser()` and lets the wrapped consumer's own `connect()` reject
    the connection explicitly (task's own "unauthorized access must be
    rejected server-side, not just frontend-hidden" — the rejection belongs
    to the consumer, which can close with a specific code; this middleware
    only ever supplies an identity, never a verdict).
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"")
        if isinstance(query_string, bytes):
            query_string = query_string.decode("utf-8", errors="ignore")
        token = parse_qs(query_string).get("token", [None])[0]

        scope = dict(scope)
        scope["user"] = await _user_from_token(token) if token else AnonymousUser()

        return await self.inner(scope, receive, send)
