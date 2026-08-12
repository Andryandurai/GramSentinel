from django.urls import path

from .views import (
    AlertDetailView,
    AlertEvidenceView,
    AlertFeedbackView,
    AlertListView,
    AlertStatusView,
    OfficerCommunityDataView,
    OfficerCommunityReportsView,
    OfficerDashboardView,
)

urlpatterns = [
    path(
        "officer/dashboard/", OfficerDashboardView.as_view(), name="officer-dashboard"
    ),
    path(
        "officer/community-data/",
        OfficerCommunityDataView.as_view(),
        name="officer-community-data",
    ),
    path(
        "officer/community-reports/",
        OfficerCommunityReportsView.as_view(),
        name="officer-community-reports",
    ),
    path("alerts/", AlertListView.as_view(), name="alert-list"),
    path("alerts/<int:pk>/", AlertDetailView.as_view(), name="alert-detail"),
    path(
        "alerts/<int:pk>/evidence/",
        AlertEvidenceView.as_view(),
        name="alert-evidence",
    ),
    path("alerts/<int:pk>/status/", AlertStatusView.as_view(), name="alert-status"),
    path(
        "alerts/<int:pk>/feedback/", AlertFeedbackView.as_view(), name="alert-feedback"
    ),
]
