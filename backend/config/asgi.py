"""ASGI entrypoint.

WebSockets are an optional enhancement (Section 36): the officer dashboard
works with plain REST polling, and the alerts consumer only pushes
already-safety-verified alert summaries.

Phase 8 adds the simulation app's own live-streaming route alongside the
existing alerts route, in the same top-level `URLRouter` — not a second
`ProtocolTypeRouter`/`"websocket"` key (ASGI only allows one). Both routes
still sit inside the one outer `AuthMiddlewareStack`, unchanged; the
simulation route additionally wraps itself in `JWTAuthMiddleware` (see
`simulation/routing.py`), so `alerts`'s own session/cookie-based auth
behaviour is completely untouched by this addition.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from alerts.routing import websocket_urlpatterns as alerts_websocket_urlpatterns  # noqa: E402
from simulation.routing import websocket_urlpatterns as simulation_websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AuthMiddlewareStack(
            URLRouter(alerts_websocket_urlpatterns + simulation_websocket_urlpatterns)
        ),
    }
)
