from django.urls import path

from .models import FieldVisitStatus, InspectionStatus
from .views import (
    ActionPlanDetailView,
    ActionPlanListCreateView,
    ActionPlanProgressView,
    FieldOperationsMetaView,
    FieldOperationsSummaryView,
    FieldVisitDetailView,
    FieldVisitListCreateView,
    FieldVisitTransitionView,
    InspectionAttachmentDownloadView,
    InspectionAttachmentListCreateView,
    InspectionDetailView,
    InspectionListCreateView,
    InspectionResponseUpdateView,
    InspectionTransitionView,
)

urlpatterns = [
    path("officer/field-operations/summary/", FieldOperationsSummaryView.as_view(), name="fieldops-summary"),
    path("officer/field-operations/meta/", FieldOperationsMetaView.as_view(), name="fieldops-meta"),
    # --- Field Visits ------------------------------------------------------
    path("officer/field-visits/", FieldVisitListCreateView.as_view(), name="field-visit-list"),
    path("officer/field-visits/<int:pk>/", FieldVisitDetailView.as_view(), name="field-visit-detail"),
    path(
        "officer/field-visits/<int:pk>/start/",
        FieldVisitTransitionView.as_view(),
        {"target": FieldVisitStatus.IN_PROGRESS},
        name="field-visit-start",
    ),
    path(
        "officer/field-visits/<int:pk>/complete/",
        FieldVisitTransitionView.as_view(),
        {"target": FieldVisitStatus.COMPLETED},
        name="field-visit-complete",
    ),
    path(
        "officer/field-visits/<int:pk>/cancel/",
        FieldVisitTransitionView.as_view(),
        {"target": FieldVisitStatus.CANCELLED},
        name="field-visit-cancel",
    ),
    # --- Inspections ---------------------------------------------------------
    path("officer/inspections/", InspectionListCreateView.as_view(), name="inspection-list"),
    path("officer/inspections/<int:pk>/", InspectionDetailView.as_view(), name="inspection-detail"),
    path(
        "officer/inspections/<int:pk>/start/",
        InspectionTransitionView.as_view(),
        {"target": InspectionStatus.IN_PROGRESS},
        name="inspection-start",
    ),
    path(
        "officer/inspections/<int:pk>/complete/",
        InspectionTransitionView.as_view(),
        {"target": InspectionStatus.COMPLETED},
        name="inspection-complete",
    ),
    path(
        "officer/inspections/<int:pk>/responses/<int:response_id>/",
        InspectionResponseUpdateView.as_view(),
        name="inspection-response-update",
    ),
    path(
        "officer/inspections/<int:pk>/attachments/",
        InspectionAttachmentListCreateView.as_view(),
        name="inspection-attachment-create",
    ),
    path(
        "officer/inspections/<int:pk>/attachments/<int:attachment_id>/",
        InspectionAttachmentDownloadView.as_view(),
        name="inspection-attachment-download",
    ),
    # --- Action Plans --------------------------------------------------------
    path("officer/action-plans/", ActionPlanListCreateView.as_view(), name="action-plan-list"),
    path("officer/action-plans/<int:pk>/", ActionPlanDetailView.as_view(), name="action-plan-detail"),
    path("officer/action-plans/<int:pk>/progress/", ActionPlanProgressView.as_view(), name="action-plan-progress"),
]
