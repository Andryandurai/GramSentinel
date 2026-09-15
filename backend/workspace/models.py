"""Work & Communication — private worker/supervisor messaging, report
approval tracking, and a correction-request workflow for already-submitted
records.

This is a deliberately separate app rather than an extension of `community`
or `assessments`: `community/models.py`'s own docstring enforces "nothing
in this module has a foreign key to patients.Patient or
assessments.PatientAssessment" as a schema-level privacy boundary, and a
correction request genuinely needs to reference a `PatientAssessment` (an
individual-layer record). Putting these models here, in their own app with
their own explicit FKs, keeps that boundary intact rather than punching a
hole in it.

Nothing here is reused by, or read by, RuralCare triage, the GramSentinel
Safety Engine, RAG, or the Simulation Lab. It is a workflow layer on top of
records those systems already produce — it never recomputes or overrides
anything they decided.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class WorkflowStatus(models.TextChoices):
    """One shared status vocabulary for both the Report Approval Tracker
    and the Correction Request System — the task's own instruction ("Use
    existing project terminology if equivalent status values already
    exist... Do NOT create duplicate status vocabularies unnecessarily")
    applied to these two new, closely related workflows rather than to an
    older feature, since neither status concept existed anywhere in the
    codebase before this."""

    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    APPROVED = "APPROVED", "Approved"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION", "Returned for correction"
    RESUBMITTED = "RESUBMITTED", "Resubmitted"
    REJECTED = "REJECTED", "Rejected"


#: Transitions a Health Officer may make. A worker may only ever move a
#: RETURNED_FOR_CORRECTION item to RESUBMITTED (enforced in the view, not
#: here) — every other transition is officer-only and enforced the same way.
OFFICER_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    WorkflowStatus.SUBMITTED: (WorkflowStatus.UNDER_REVIEW,),
    WorkflowStatus.RESUBMITTED: (WorkflowStatus.UNDER_REVIEW,),
    WorkflowStatus.UNDER_REVIEW: (
        WorkflowStatus.APPROVED,
        WorkflowStatus.RETURNED_FOR_CORRECTION,
        WorkflowStatus.REJECTED,
    ),
}


class SupervisorMessage(models.Model):
    """One message in the private conversation between a Health Worker and
    their assigned Health Officer.

    There is no separate `Conversation` model: `worker` + `officer` are set
    once per thread (both server-derived — see `workspace.services
    .assigned_officer_for`) and never change, so "the conversation" is
    simply every `SupervisorMessage` row sharing that pair. A village has
    exactly one Health Officer in this project's current data, so this is
    not a simplification that loses anything real; if a village ever gained
    more than one officer, `assigned_officer_for` (the one place this
    lookup happens) is where that would need to change, not this model.
    """

    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    #: Denormalised from `worker.village` at send time — never trusted from
    #: the client, never itself the source of scoping (queries still filter
    #: through `worker`/`officer`), but indexed so a village-wide query
    #: never has to join through `worker` first.
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="+"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )

    subject = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(max_length=8000)

    #: Same data-URI-on-the-row convention `users.photos` already
    #: established for profile photographs — the one existing secure
    #: file-handling mechanism in this codebase — extended to document
    #: types in `workspace.attachments`. Never a filesystem path, never a
    #: public media URL.
    attachment = models.TextField(blank=True, default="")
    attachment_filename = models.CharField(max_length=200, blank=True, default="")
    attachment_mime = models.CharField(max_length=100, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["worker", "created_at"]),
            models.Index(fields=["officer", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Message #{self.pk} {self.sender_id} -> thread(worker={self.worker_id})"

    @property
    def recipient_id(self) -> int:
        return self.officer_id if self.sender_id == self.worker_id else self.worker_id


class ReportApproval(models.Model):
    """The current approval state of one `community.CommunityReport`.

    A worker resubmitting the same village/week already updates the SAME
    `CommunityReport` row in place (see `community/views.py`'s own
    `update_or_create` on `(village, week_label, worker)`), so a
    one-to-one here is exactly right — there is one current approval state
    per report, and its full transition history lives in
    `ReportApprovalEvent` below, not in a second `CommunityReport` row.
    """

    report = models.OneToOneField(
        "community.CommunityReport", on_delete=models.CASCADE, related_name="approval"
    )
    #: Denormalised from `report.village`/`report.worker` — same rationale
    #: as `SupervisorMessage.village` above.
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="+"
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    status = models.CharField(
        max_length=32, choices=WorkflowStatus.choices, default=WorkflowStatus.SUBMITTED
    )
    supervisor_comment = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["village", "status"])]

    def __str__(self) -> str:
        return f"Approval for report #{self.report_id}: {self.status}"


class ReportApprovalEvent(models.Model):
    """Append-only transition history for one `ReportApproval` — the audit
    trail the task requires ("Preserve comment history where the existing
    architecture supports it"). Never edited or deleted once written."""

    approval = models.ForeignKey(
        ReportApproval, on_delete=models.CASCADE, related_name="events"
    )
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, choices=WorkflowStatus.choices)
    comment = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.from_status or '—'} -> {self.to_status}"


#: Record types a worker may currently request a correction against —
#: deliberately a short, explicit allowlist (task §"Correction Request
#: System": "Determine exactly which record types are currently safe and
#: appropriate") rather than an open "any model" mechanism. Both already
#: carry a `worker` FK and a `village` FK, which is what makes ownership
#: and village-scope enforcement possible without per-model special-casing.
CORRECTABLE_MODELS = ("assessments.patientassessment", "community.communityreport")


class CorrectionRequest(models.Model):
    """A worker's request to correct an already-submitted, locked record.

    Deliberately NOT an edit of the original record: `content_type` +
    `object_id` point at it read-only, and `original_snapshot` freezes a
    plain-language summary of the record's current state at request time
    so the request stays meaningful even if the underlying record is later
    superseded (the same "denormalise for traceability" convention
    `community.LocalSignalReport` already uses for the signal it flags).

    Approving a request never silently rewrites the original record's own
    columns (see `workspace/services.py::apply_correction_effect` for
    exactly what "approved" does mean) — there is no generic field-patching
    engine here, on purpose: the form this model backs collects free-text
    "what is wrong" and "what it should be", not a structured field/value
    pair a machine could safely apply unattended.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    record = GenericForeignKey("content_type", "object_id")

    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="+"
    )
    record_label = models.CharField(
        max_length=120,
        help_text="Plain-language identifier, e.g. 'Assessment #1024' — never a patient name.",
    )
    original_snapshot = models.JSONField(
        default=dict,
        help_text="Plain-language field/value pairs as they stood when this request was made.",
    )

    mistake_description = models.TextField(max_length=4000)
    proposed_correction = models.TextField(max_length=4000)

    status = models.CharField(
        max_length=32, choices=WorkflowStatus.choices, default=WorkflowStatus.SUBMITTED
    )
    supervisor_comment = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    applied_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Set when an APPROVED correction's effect (see "
            "services.apply_correction_effect) has been carried out."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["village", "status"]),
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"Correction #{self.pk} for {self.record_label}: {self.status}"


class CorrectionEvent(models.Model):
    """Append-only transition history for one `CorrectionRequest` — mirrors
    `ReportApprovalEvent` exactly, same rationale."""

    correction = models.ForeignKey(
        CorrectionRequest, on_delete=models.CASCADE, related_name="events"
    )
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, choices=WorkflowStatus.choices)
    comment = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.from_status or '—'} -> {self.to_status}"
