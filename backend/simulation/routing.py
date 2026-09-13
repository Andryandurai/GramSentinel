"""Phase 8 — simulation WebSocket routes.

Mirrors `alerts/routing.py`'s own shape exactly. The one difference:
`OfficerAlertConsumer.as_asgi()` there relies solely on the outer
`AuthMiddlewareStack` (`config/asgi.py`) for auth; here `JWTAuthMiddleware`
wraps just this one route, since the simulation consumer needs the same
JWT-bearer identity the REST API already uses — see `ws_auth.py`'s module
docstring for why. `alerts`'s route and behaviour are completely untouched.
"""

from django.urls import path

from .consumers import SimulationSessionConsumer
from .ws_auth import JWTAuthMiddleware

websocket_urlpatterns = [
    path(
        "ws/simulation/sessions/<int:session_id>/",
        JWTAuthMiddleware(SimulationSessionConsumer.as_asgi()),
    ),
]
