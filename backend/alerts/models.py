"""Alerts, the evidence behind them, and the human decisions that follow."""

import uuid

from django.conf import settings
from django.db import models

from core.constants import (
    DataQuality,
    EvidenceStatus,
    SafetyVerdict,
    SignalCategory,
    SourceKind,
)


class AgentRun(models.Model):
    """One agent invocation, recorded so handoffs are inspectable after the fact.

    This is what makes 'genuinely multi-agent' checkable rather than asserted:
    each row names the agent, the pipeline stage, what it received and what it
    produced.
    """

    run_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    stage = models.CharField(max_length=48)
    agent_name = models.CharField(max_length=64)
    agent_layer = models.CharField(max_length=32, blank=True)
    village = models.ForeignKey(
        "core.Village",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_runs",
    )
    week_label = models.CharField(max_length=16, blank=True)
    sequence = models.PositiveSmallIntegerField(default=0)
    input_summary = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, default="OK")
    duration_ms = models.FloatField(default=0.0)
    used_llm = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run_id", "sequence"]

    def __str__(self) -> str:
        return f"{self.stage}/{self.agent_name} ({self.status})"


class Alert(models.Model):
    """A potential community health pattern raised for human attention.

    Never a conclusion, never an outbreak declaration — a request for a
    qualified human to look, with the evidence attached.
    """

    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MODERATE = "MODERATE", "Moderate"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        DETECTED = "DETECTED", "Detected"
        UNDER_INVESTIGATION = "UNDER_INVESTIGATION", "Under investigation"
        CLOSED = "CLOSED", "Closed"

    alert_uid = models.UUIDField(default=uuid.uuid4, unique=True)
    village = models.ForeignKey(
        "core.Village", on_delete=models.PROTECT, related_name="alerts"
    )
    cluster = models.CharField(max_length=120)
    category = models.CharField(max_length=32, choices=SignalCategory.choices)
    week_label = models.CharField(max_length=16)
    period_start = models.DateField()
    period_end = models.DateField()

    title = models.CharField(max_length=200)
    summary = models.TextField(
        help_text="Plain-language narrative. Screened for prohibited claims."
    )
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.MODERATE
    )
    confidence = models.FloatField(default=0.0)
    corroborating_source_count = models.PositiveSmallIntegerField(default=0)

    cross_level_verdict = models.CharField(max_length=32, blank=True)
    cross_level_statement = models.TextField(blank=True)

    safety_verdict = models.CharField(
        max_length=16, choices=SafetyVerdict.choices, default=SafetyVerdict.DOWNGRADE
    )
    safety_status = models.CharField(max_length=48, blank=True)

    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.DETECTED
    )
    orchestration_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    narrative_used_llm = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self) -> str:
        return f"{self.title} [{self.severity}/{self.status}]"

    @property
    def requires_human_review(self) -> bool:
        """Structural, not configurable. Rule 7 has no satisfied state."""
        return True


class AlertEvidence(models.Model):
    """One source's structured evidence card, as shown in the Evidence View."""

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="evidence")
    source_kind = models.CharField(max_length=32, choices=SourceKind.choices)
    source_name = models.CharField(max_length=160)
    category = models.CharField(max_length=32, choices=SignalCategory.choices)
    village_code = models.CharField(max_length=32)
    week_label = models.CharField(max_length=16)

    baseline = models.FloatField(null=True, blank=True)
    current_value = models.FloatField(null=True, blank=True)
    change_pct = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    data_quality = models.CharField(
        max_length=16, choices=DataQuality.choices, default=DataQuality.GOOD
    )
    status = models.CharField(max_length=24, choices=EvidenceStatus.choices)
    is_corroborating = models.BooleanField(
        default=False,
        help_text="Counts toward the two-independent-source rule. Weather does not.",
    )
    explanation = models.TextField(blank=True)
    produced_by_agent = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ["source_kind"]

    def __str__(self) -> str:
        return f"{self.source_kind} {self.status}"


class SafetyCheck(models.Model):
    """A recorded run of the deterministic engine, rule by rule."""

    class Scope(models.TextChoices):
        COMMUNITY = "COMMUNITY", "Community"
        INDIVIDUAL = "INDIVIDUAL", "Individual"

    alert = models.ForeignKey(
        Alert,
        on_delete=models.CASCADE,
        related_name="safety_checks",
        null=True,
        blank=True,
        help_text="Null when the hypothesis was BLOCKed and no alert was raised.",
    )
    assessment = models.ForeignKey(
        "assessments.PatientAssessment",
        on_delete=models.CASCADE,
        related_name="safety_checks",
        null=True,
        blank=True,
    )
    scope = models.CharField(max_length=16, choices=Scope.choices)
    verdict = models.CharField(max_length=16, choices=SafetyVerdict.choices)
    passed = models.BooleanField(default=False)
    status = models.CharField(max_length=48)
    rules = models.JSONField(default=list)
    reasons = models.JSONField(default=list)
    engine_version = models.CharField(max_length=16, default="1.0.0")
    village = models.ForeignKey(
        "core.Village", on_delete=models.SET_NULL, null=True, blank=True
    )
    week_label = models.CharField(max_length=16, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"SafetyCheck {self.scope} {self.verdict}"


class Investigation(models.Model):
    class Status(models.TextChoices):
        UNDER_INVESTIGATION = "UNDER_INVESTIGATION", "Under investigation"
        MONITORING = "MONITORING", "Monitoring"
        MORE_DATA_REQUESTED = "MORE_DATA_REQUESTED", "More data requested"
        COMPLETED = "COMPLETED", "Completed"

    alert = models.OneToOneField(
        Alert, on_delete=models.CASCADE, related_name="investigation"
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.UNDER_INVESTIGATION
    )
    notes = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Investigation of {self.alert_id} [{self.status}]"


class Feedback(models.Model):
    """The officer's recorded outcome — Stage 6, and the honesty mechanism.

    'Valid Signal' means a human confirmed the alert was worth raising. It does
    not mean any disease or outbreak was confirmed.
    """

    class Outcome(models.TextChoices):
        VALID_SIGNAL = "VALID_SIGNAL", "Valid signal"
        FALSE_ALERT = "FALSE_ALERT", "False alert"
        RESOLVED = "RESOLVED", "Resolved"

    alert = models.OneToOneField(
        Alert, on_delete=models.CASCADE, related_name="feedback"
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    outcome = models.CharField(max_length=24, choices=Outcome.choices)
    notes = models.TextField(blank=True)
    resolution_latency_seconds = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Feedback {self.outcome} for alert {self.alert_id}"
