from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def root(_request):
    """Backend status landing page at "/".

    This is not, and must not become, the React frontend — the frontend is a
    separate Render Static Site with its own origin. This exists only so a
    browser or health probe hitting the backend's bare domain gets a plain
    JSON acknowledgement instead of a 404 (Django has no route for "/" unless
    one is declared, since the frontend has always lived elsewhere).
    """
    return JsonResponse({"service": "GramSentinel", "status": "running"})


def health(_request):
    return JsonResponse(
        {
            "service": "GramSentinel",
            "description": (
                "Rural Healthcare Intelligence & Community Early-Warning Platform"
            ),
            "status": "ok",
            "data_notice": "Prototype. Synthetic / public / anonymised data only.",
            "disclaimer": (
                "Decision-support only. Does not replace professional medical "
                "care. Human approval required."
            ),
        }
    )


urlpatterns = [
    path("", root, name="root"),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("users.urls")),
    path("api/", include("core.urls")),
    path("api/", include("patients.urls")),
    path("api/", include("assessments.urls")),
    path("api/", include("community.urls")),
    path("api/", include("alerts.urls")),
]
