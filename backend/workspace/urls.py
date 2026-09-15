from django.urls import path

from .views import (
    CorrectableRecordListView,
    CorrectionDetailView,
    MessageAttachmentView,
    MessageMarkReadView,
    OfficerCorrectionListView,
    OfficerCorrectionTransitionView,
    OfficerMessageThreadListView,
    OfficerMessageThreadView,
    OfficerReportApprovalListView,
    OfficerReportApprovalTransitionView,
    WorkerCorrectionListCreateView,
    WorkerMessageThreadView,
    WorkerReportApprovalListView,
)

urlpatterns = [
    # --- Worker side: Work & Communication -------------------------------
    path("work/messages/", WorkerMessageThreadView.as_view(), name="work-messages"),
    path("work/messages/<int:message_id>/read/", MessageMarkReadView.as_view(), name="work-message-read"),
    path(
        "work/messages/<int:message_id>/attachment/",
        MessageAttachmentView.as_view(),
        name="work-message-attachment",
    ),
    path("work/report-approvals/", WorkerReportApprovalListView.as_view(), name="work-report-approvals"),
    path("work/correctable-records/", CorrectableRecordListView.as_view(), name="work-correctable-records"),
    path("work/corrections/", WorkerCorrectionListCreateView.as_view(), name="work-corrections"),
    path("work/corrections/<int:pk>/", CorrectionDetailView.as_view(), name="work-correction-detail"),
    # --- Officer side: reviewing worker requests --------------------------
    path("officer/work/threads/", OfficerMessageThreadListView.as_view(), name="officer-work-threads"),
    path(
        "officer/work/threads/<int:worker_id>/messages/",
        OfficerMessageThreadView.as_view(),
        name="officer-work-thread-messages",
    ),
    path(
        "officer/work/report-approvals/",
        OfficerReportApprovalListView.as_view(),
        name="officer-work-report-approvals",
    ),
    path(
        "officer/work/report-approvals/<int:pk>/transition/",
        OfficerReportApprovalTransitionView.as_view(),
        name="officer-work-report-approval-transition",
    ),
    path("officer/work/corrections/", OfficerCorrectionListView.as_view(), name="officer-work-corrections"),
    path(
        "officer/work/corrections/<int:pk>/transition/",
        OfficerCorrectionTransitionView.as_view(),
        name="officer-work-correction-transition",
    ),
]
