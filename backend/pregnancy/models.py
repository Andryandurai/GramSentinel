"""Pregnancy / Maternal Health follow-up — Health Worker Assessment extension.

Inspired by the Pregnancy and Infant Cohort Monitoring and Evaluation (PICME)
concept used in Tamil Nadu. This project is NOT directly integrated with the
Government of Tamil Nadu PICME system. `picme_rch_id` records an ID already
issued to the citizen through the appropriate government process — nothing
here generates, guesses, or fabricates an official PICME/RCH number.

Deliberately a separate app from `assessments`/`patients` rather than an
extension of `PatientAssessment`: pregnancy visits use a fixed, per-visit
question set (`pregnancy.questionnaire`) with no numeric triage score, and
folding them into `PatientAssessment.symptoms` (documented there as
"normalised symptom codes" feeding the general triage/community-signal
pipeline) would misrepresent pregnancy follow-up responses as general
symptom reports. `Patient` itself is reused unchanged — no duplicate
patient record.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class PregnancyVisitNumber(models.IntegerChoices):
    VISIT_1 = 1, "Visit 1 - First Pregnancy Visit"
    VISIT_2 = 2, "Visit 2 - Follow-up ANC Visit"
    VISIT_3 = 3, "Visit 3 - Baby Movement / Risk Check"
    VISIT_4 = 4, "Visit 4 - Delivery Preparation"


class PicmeRchStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", "Available"
    REGISTRATION_PENDING = "REGISTRATION_PENDING", "Registration Pending"
    NOT_AVAILABLE = "NOT_AVAILABLE", "Not Available"


class PregnancyStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    COMPLETED = "COMPLETED", "Completed"
    TRANSFERRED = "TRANSFERRED", "Transferred"
    CLOSED = "CLOSED", "Closed"


class QuestionResponse(models.TextChoices):
    YES = "YES", "Yes"
    NO = "NO", "No"
    UNKNOWN = "UNKNOWN", "Unknown / Not reported"


class PregnancyProfile(models.Model):
    """One pregnancy episode for a patient. A patient may have more than one
    over time (history), but at most one `ACTIVE` profile at once — enforced
    both at the database level (constraint below) and again in
    `pregnancy.services` before creating a new one (the same "two
    independent checks" pattern `simulation.permissions`/`simulation
    .services` already use for village scope)."""

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="pregnancy_profiles"
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="pregnancy_profiles"
    )

    # --- PICME / RCH — externally issued, never generated here ------------
    picme_rch_id = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "The PICME/RCH ID already provided to the citizen through the "
            "appropriate government registration process. Never generated "
            "by this system."
        ),
    )
    picme_rch_status = models.CharField(
        max_length=24,
        choices=PicmeRchStatus.choices,
        default=PicmeRchStatus.NOT_AVAILABLE,
    )

    # --- Dates. Every one of these is either explicitly entered by a
    # worker/clinician or left NULL — never inferred or fabricated. --------
    lmp = models.DateField(
        null=True, blank=True, help_text="Last menstrual period, if known."
    )
    expected_delivery_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Only stored if already known from an existing clinical record. "
            "This system does not calculate or guess an EDD."
        ),
    )
    registration_date = models.DateField(default=timezone.localdate)
    next_checkup_date = models.DateField(null=True, blank=True)

    assigned_health_worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_pregnancies",
    )

    status = models.CharField(
        max_length=16, choices=PregnancyStatus.choices, default=PregnancyStatus.ACTIVE
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["village", "status"]),
            models.Index(fields=["patient", "status"]),
            models.Index(fields=["next_checkup_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["patient"],
                condition=Q(status=PregnancyStatus.ACTIVE),
                name="unique_active_pregnancy_per_patient",
            )
        ]

    def __str__(self) -> str:
        return f"Pregnancy profile #{self.pk} — {self.patient.patient_code} [{self.status}]"


class PregnancyVisitAssessment(models.Model):
    """One recorded pregnancy visit. `questionnaire_responses` only ever
    contains keys from `pregnancy.questionnaire.VISIT_QUESTIONS[visit_number]`
    — validated in the serializer, never accepted as free-form. Missing
    answers are `QuestionResponse.UNKNOWN`, never coerced to NO/0 (mirrors
    Safety Engine R8 / `InspectionChecklistResponse`'s own "missing is never
    a real value" convention)."""

    pregnancy_profile = models.ForeignKey(
        PregnancyProfile, on_delete=models.CASCADE, related_name="visits"
    )
    visit_number = models.PositiveSmallIntegerField(choices=PregnancyVisitNumber.choices)
    visit_date = models.DateField(default=timezone.localdate)

    questionnaire_responses = models.JSONField(
        default=dict,
        blank=True,
        help_text="{question_key: 'YES'/'NO'/'UNKNOWN'}, keys fixed per visit_number.",
    )

    next_checkup_date = models.DateField(null=True, blank=True)

    # Deterministic rule flags (pregnancy.rules), snapshotted at recording
    # time — never recomputed retroactively when rules or the clock change.
    warning_signs = models.JSONField(
        default=list, blank=True, help_text="Question keys answered YES to a warning-sign question."
    )
    rule_flags = models.JSONField(default=list, blank=True)

    # AI guidance snapshot (advisory only — see agents.pregnancy.guidance).
    ai_guidance = models.JSONField(default=dict, blank=True)
    llm_used = models.BooleanField(default=False)

    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="pregnancy_visits"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["visit_date", "id"]
        indexes = [models.Index(fields=["pregnancy_profile", "visit_number"])]

    def __str__(self) -> str:
        return f"Visit {self.visit_number} — profile #{self.pregnancy_profile_id}"


class PregnancyProfileEvent(models.Model):
    """Append-only audit trail for one pregnancy profile — the same shape as
    `workspace.ReportApprovalEvent`/`fieldops.ActionPlanProgressUpdate`
    (task §33: "use existing audit infrastructure"; this codebase's actual
    convention is a dedicated append-only event table per domain, not one
    shared table — `knowledge.RagQueryLog` is the same pattern applied to
    RAG). Never updated or deleted once written."""

    class EventType(models.TextChoices):
        PROFILE_CREATED = "PROFILE_CREATED", "Pregnancy profile created"
        PICME_UPDATED = "PICME_UPDATED", "PICME/RCH ID updated"
        VISIT_RECORDED = "VISIT_RECORDED", "Pregnancy visit recorded"
        NEXT_CHECKUP_CHANGED = "NEXT_CHECKUP_CHANGED", "Next check-up date changed"
        STATUS_CHANGED = "STATUS_CHANGED", "Pregnancy status changed"
        FOLLOWUP_TASK_CREATED = "FOLLOWUP_TASK_CREATED", "Health worker follow-up requested"
        COMMUNITY_REPORT_SUBMITTED = (
            "COMMUNITY_REPORT_SUBMITTED",
            "Pregnancy community report submitted",
        )

    pregnancy_profile = models.ForeignKey(
        PregnancyProfile, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    detail = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["pregnancy_profile", "created_at"])]

    def __str__(self) -> str:
        return f"{self.event_type} — profile #{self.pregnancy_profile_id}"


class PregnancyCommunityReport(models.Model):
    """Pregnancy-specific detail for a `community.CommunityReport` whose
    `report_type` is `PREGNANCY` (Pregnancy Reporting in Community Report).

    Lives here, not in `community/models.py`, on purpose: that module's own
    docstring declares a schema-level privacy boundary — nothing there has a
    foreign key to `patients.Patient` or a patient-linked profile. This app
    already legitimately holds that FK (`PregnancyProfile.patient`), so the
    `OneToOneField` back to `CommunityReport` is what lets a pregnancy report
    reference the real record without adding a patient-linked FK to the
    community layer itself.

    Every snapshot field here is derived server-side from the linked
    `PregnancyProfile`/its visits at submission time (see
    `pregnancy.services.create_pregnancy_community_report`) — never typed in
    by the worker a second time, and never a live join an officer's read
    could see drift from what was true when the report was filed.
    """

    community_report = models.OneToOneField(
        "community.CommunityReport",
        on_delete=models.CASCADE,
        related_name="pregnancy_detail",
    )
    pregnancy_profile = models.ForeignKey(
        PregnancyProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_reports",
    )

    completed_visit_count = models.PositiveSmallIntegerField(default=0)
    last_checkup_date = models.DateField(null=True, blank=True)
    next_checkup_date = models.DateField(null=True, blank=True)
    follow_up_required = models.BooleanField(
        default=False,
        help_text=(
            "Derived from pregnancy.rules.evaluate_profile_rules at "
            "submission time (FOLLOW_UP_OVERDUE / URGENT_CLINICAL_REVIEW) — "
            "never a worker's own free-text judgement."
        ),
    )

    reason = models.TextField(help_text="Why this report is being raised.")
    remarks = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Pregnancy community report — community report #{self.community_report_id}"
