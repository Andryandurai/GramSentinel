from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


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
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("users.urls")),
    path("api/", include("core.urls")),
    path("api/", include("patients.urls")),
    path("api/", include("assessments.urls")),
    path("api/", include("community.urls")),
    path("api/", include("alerts.urls")),
]
