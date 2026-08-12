from django.urls import path

from .views import (
    AssessmentDetailView,
    AssessmentListCreateView,
    AssessmentPreviewView,
    AssessmentTraceView,
    FollowUpDetailView,
    FollowUpListCreateView,
    WorkerDashboardView,
)

urlpatterns = [
    path("worker/dashboard/", WorkerDashboardView.as_view(), name="worker-dashboard"),
    path("assessments/", AssessmentListCreateView.as_view(), name="assessment-list"),
    path(
        "assessments/preview/",
        AssessmentPreviewView.as_view(),
        name="assessment-preview",
    ),
    path(
        "assessments/<int:pk>/",
        AssessmentDetailView.as_view(),
        name="assessment-detail",
    ),
    path(
        "assessments/<int:pk>/trace/",
        AssessmentTraceView.as_view(),
        name="assessment-trace",
    ),
    path("followups/", FollowUpListCreateView.as_view(), name="followup-list"),
    path("followups/<int:pk>/", FollowUpDetailView.as_view(), name="followup-detail"),
]
