"""Patient assessments and follow-ups (individual layer)."""

from django.conf import settings
from django.db import models

from core.constants import SignalCategory, TriageLevel


class PatientAssessment(models.Model):
    """One encounter, plus the RuralCare agent chain's structured output.

    The stored output is triage-level decision support: a level, a reasoning
    summary and a suggested workflow. It is never a diagnosis.
    """

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="assessments"
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="assessments",
    )
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="assessments"
    )

    # --- Worker-entered information -------------------------------------
    symptoms = models.JSONField(default=list, help_text="Normalised symptom codes.")
    raw_symptom_text = models.TextField(blank=True)
    duration_days = models.PositiveSmallIntegerField(default=0)
    temperature_c = models.FloatField(null=True, blank=True)
    pulse_bpm = models.PositiveSmallIntegerField(null=True, blank=True)
    respiratory_rate = models.PositiveSmallIntegerField(null=True, blank=True)
    systolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    diastolic_bp = models.PositiveSmallIntegerField(null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField(null=True, blank=True)
    history = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    # --- Agent chain output ---------------------------------------------
    primary_category = models.CharField(
        max_length=32,
        choices=SignalCategory.choices,
        default=SignalCategory.OTHER,
        help_text="Drives which aggregated community signal this contributes to.",
    )
    triage_level = models.CharField(
        max_length=16, choices=TriageLevel.choices, default=TriageLevel.ROUTINE
    )
    triage_score = models.FloatField(default=0.0)
    reasoning_summary = models.TextField(blank=True)
    referral_recommendation = models.TextField(blank=True)
    followup_interval_days = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- Individual Safety Agent (deterministic) -------------------------
    red_flags = models.JSONField(default=list, blank=True)
    escalation_forced = models.BooleanField(
        default=False,
        help_text="True when the deterministic red-flag rule set overrode the model.",
    )
    safety_status = models.CharField(max_length=48, blank=True)

    # --- Traceability -----------------------------------------------------
    agent_trace = models.JSONField(
        default=list,
        blank=True,
        help_text="Ordered record of each agent's input summary and output.",
    )
    llm_used = models.BooleanField(default=False)

    is_draft = models.BooleanField(
        default=False,
        help_text="True for a preview run that the worker has not submitted yet.",
    )
    aggregated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this encounter was folded into an anonymised community signal.",
    )
    encounter_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Assessment #{self.pk} {self.patient.patient_code} [{self.triage_level}]"


class FollowUp(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        MISSED = "MISSED", "Missed"

    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE, related_name="followups"
    )
    assessment = models.ForeignKey(
        PatientAssessment,
        on_delete=models.CASCADE,
        related_name="followups",
        null=True,
        blank=True,
    )
    due_date = models.DateField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date"]

    def __str__(self) -> str:
        return f"Follow-up {self.patient.patient_code} due {self.due_date}"
