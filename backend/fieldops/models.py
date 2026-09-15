"""Field Operations — Field Visit Planner, Inspection Checklist System, and
Action Plan Management. Operational Health Officer workflow, deliberately
separate from GramSentinel's own detection/triage layer: nothing here
reads from or writes to `alerts.Alert`, `community.CommunitySignal`,
`safety.SafetyEngine`, `simulation.*`, or `knowledge.*` (RAG). A Health
Officer creates a visit, an inspection, or an action plan by their own
explicit action — this module never generates one automatically from a
detected signal.

Honesty note (mirrors `knowledge/seed_content.py`'s own disclaimer for the
RAG knowledge base): the checklist items seeded below are prototype,
configurable inspection items suitable for this demonstration — they are
not transcribed from, and must never be presented as, an official
government inspection standard.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Priority(models.TextChoices):
    """Shared by FieldVisit and ActionPlan — one vocabulary, not two."""

    NORMAL = "NORMAL", "Normal"
    HIGH = "HIGH", "High"
    URGENT = "URGENT", "Urgent"


# ---------------------------------------------------------------------------
# Field Visit Planner
# ---------------------------------------------------------------------------
class FieldVisitStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Scheduled"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    # Not a value ever stored server-side by a status write — see
    # `services.py::is_overdue()`. Included in the choices only so the
    # serializer's `status` output can legitimately show it without a
    # second, parallel field.


#: Allowed manual status transitions — the same "fixed table, not a
#: caller-supplied rule" shape `workspace.models.OFFICER_ALLOWED_TRANSITIONS`
#: already established for Work & Communication (task's own "do not allow
#: arbitrary client-defined status values").
FIELD_VISIT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    FieldVisitStatus.SCHEDULED: (FieldVisitStatus.IN_PROGRESS, FieldVisitStatus.CANCELLED),
    FieldVisitStatus.IN_PROGRESS: (FieldVisitStatus.COMPLETED, FieldVisitStatus.CANCELLED),
}

#: Selectable starting points for "Visit Objective" — a convenience list,
#: never a closed vocabulary: `FieldVisit.objective` is a free-text field,
#: so a custom objective is always possible too (task: "Also allow custom
#: objective text").
VISIT_OBJECTIVE_TEMPLATES = (
    "Routine village health inspection",
    "Follow-up on sanitation issue",
    "Verify reported local signal",
    "Drinking water assessment",
    "School health inspection",
    "Anganwadi inspection",
    "Follow-up on corrective action",
    "Community health review",
)


class FieldVisit(models.Model):
    village = models.ForeignKey("core.Village", on_delete=models.PROTECT, related_name="field_visits")
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="field_visits"
    )

    visit_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    objective = models.CharField(max_length=300)
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField(max_length=16, choices=FieldVisitStatus.choices, default=FieldVisitStatus.SCHEDULED)
    notes = models.TextField(blank=True, default="")

    # --- Visit outcome (filled in on/after completion) --------------------
    outcome_summary = models.TextField(blank=True, default="")
    observations = models.TextField(blank=True, default="")
    issues_identified = models.TextField(blank=True, default="")
    follow_up_required = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-visit_date", "-id"]
        indexes = [
            models.Index(fields=["village", "status"]),
            models.Index(fields=["visit_date"]),
            models.Index(fields=["assigned_officer"]),
        ]

    def __str__(self) -> str:
        return f"Field visit #{self.pk} — {self.village.code} {self.visit_date}"

    @property
    def is_overdue(self) -> bool:
        """Never stored — always computed, so it can never drift out of
        sync with the clock (task's own explicit preference)."""

        if self.status in (FieldVisitStatus.COMPLETED, FieldVisitStatus.CANCELLED):
            return False
        return self.visit_date < timezone.localdate()


# ---------------------------------------------------------------------------
# Inspection Checklist System
# ---------------------------------------------------------------------------
class InspectionType(models.TextChoices):
    """The four categories the feature specification explicitly requires —
    a closed set, on purpose (task: "Do not invent unrelated categories")."""

    DRINKING_WATER_SANITATION = "DRINKING_WATER_SANITATION", "Drinking Water & Sanitation"
    SCHOOL_ANGANWADI = "SCHOOL_ANGANWADI", "School & Anganwadi"
    PUBLIC_PLACE_HYGIENE = "PUBLIC_PLACE_HYGIENE", "Public-Place Hygiene"
    WASTE_MANAGEMENT = "WASTE_MANAGEMENT", "Waste Management"


class InspectionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"


INSPECTION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    InspectionStatus.DRAFT: (InspectionStatus.IN_PROGRESS,),
    InspectionStatus.IN_PROGRESS: (InspectionStatus.COMPLETED,),
}


class ChecklistItemStatus(models.TextChoices):
    """Exactly the three values the task requires — deliberately not the
    ambiguous Good/Average/Poor scale nothing in this codebase already
    uses."""

    PASSED = "PASSED", "Passed"
    FAILED = "FAILED", "Failed"
    NEEDS_ACTION = "NEEDS_ACTION", "Needs action"


class ChecklistItemTemplate(models.Model):
    """A reusable checklist item definition — inspections reference these
    rather than each carrying its own free-standing copy of the question
    text, so the item vocabulary lives in exactly one place (task's own
    "prefer a reusable checklist architecture" instruction)."""

    category = models.CharField(max_length=32, choices=InspectionType.choices)
    text = models.CharField(max_length=300)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "order", "id"]
        indexes = [models.Index(fields=["category", "is_active"])]

    def __str__(self) -> str:
        return f"[{self.category}] {self.text}"


class Inspection(models.Model):
    village = models.ForeignKey("core.Village", on_delete=models.PROTECT, related_name="inspections")
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="inspections"
    )
    inspection_type = models.CharField(max_length=32, choices=InspectionType.choices)
    inspection_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=16, choices=InspectionStatus.choices, default=InspectionStatus.DRAFT)
    summary_remarks = models.TextField(blank=True, default="")

    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-inspection_date", "-id"]
        indexes = [
            models.Index(fields=["village", "status"]),
            models.Index(fields=["inspection_type"]),
        ]

    def __str__(self) -> str:
        return f"Inspection #{self.pk} — {self.get_inspection_type_display()} ({self.village.code})"


class InspectionChecklistResponse(models.Model):
    """One row per checklist item, auto-created (unanswered) the moment an
    `Inspection` is created for a category — see `services.py::
    create_inspection()`. `status` is nullable to represent "not yet
    reviewed", structurally distinct from any of the three real answers,
    matching this codebase's established "missing is never coerced into a
    real value" convention (Safety Engine R8, LocalSignalReport, etc.)."""

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="responses")
    template_item = models.ForeignKey(ChecklistItemTemplate, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=16, choices=ChecklistItemStatus.choices, null=True, blank=True)
    remarks = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["template_item__order", "id"]
        unique_together = [("inspection", "template_item")]

    def __str__(self) -> str:
        return f"{self.template_item.text}: {self.status or 'not reviewed'}"


class InspectionAttachment(models.Model):
    """Inspection-level (not per-item — task's own stated preference when
    the architecture doesn't already support item-level files, which this
    one doesn't). Reuses `workspace.attachments.validate_attachment` byte
    for byte — the same data-URI, paranoid-signature mechanism, not a
    second file-handling implementation."""

    inspection = models.ForeignKey(Inspection, on_delete=models.CASCADE, related_name="attachments")
    file = models.TextField()
    filename = models.CharField(max_length=200, blank=True, default="")
    mime = models.CharField(max_length=100, blank=True, default="")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.filename or f"Attachment #{self.pk}"


# ---------------------------------------------------------------------------
# Action Plan Management
# ---------------------------------------------------------------------------
class Department(models.Model):
    """A minimal, genuinely configurable structure — task's own fallback
    ("If no Department model exists, create a minimal configurable
    structure") since no Department concept existed anywhere in the
    project before this. Editable through Django admin; not a hardcoded
    enum, so a new department never requires a code change."""

    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class ActionPlanStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"


class ActionPlanSourceType(models.TextChoices):
    FIELD_VISIT = "FIELD_VISIT", "Field visit"
    INSPECTION = "INSPECTION", "Inspection"
    OTHER = "OTHER", "Other operational issue"


class ActionPlan(models.Model):
    village = models.ForeignKey("core.Village", on_delete=models.PROTECT, related_name="action_plans")
    title = models.CharField(max_length=200)
    problem_finding = models.TextField()

    source_type = models.CharField(max_length=16, choices=ActionPlanSourceType.choices, default=ActionPlanSourceType.OTHER)
    source_field_visit = models.ForeignKey(
        FieldVisit, on_delete=models.SET_NULL, null=True, blank=True, related_name="action_plans"
    )
    source_inspection = models.ForeignKey(
        Inspection, on_delete=models.SET_NULL, null=True, blank=True, related_name="action_plans"
    )
    source_checklist_item = models.ForeignKey(
        InspectionChecklistResponse, on_delete=models.SET_NULL, null=True, blank=True, related_name="action_plans"
    )

    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="action_plans")
    responsible_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    deadline = models.DateField()
    required_resources = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=16, choices=Priority.choices, default=Priority.NORMAL)

    progress_percentage = models.PositiveSmallIntegerField(
        default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    status = models.CharField(max_length=16, choices=ActionPlanStatus.choices, default=ActionPlanStatus.PENDING)
    notes = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["deadline", "-id"]
        indexes = [
            models.Index(fields=["village", "status"]),
            models.Index(fields=["deadline"]),
            models.Index(fields=["department"]),
        ]

    def __str__(self) -> str:
        return f"Action plan #{self.pk} — {self.title}"

    @property
    def is_overdue(self) -> bool:
        return self.status != ActionPlanStatus.COMPLETED and self.deadline < timezone.localdate()


class ActionPlanProgressUpdate(models.Model):
    """Append-only — progress history is never silently overwritten (task's
    own explicit requirement), mirroring `workspace.models
    .ReportApprovalEvent`'s same append-only shape."""

    action_plan = models.ForeignKey(ActionPlan, on_delete=models.CASCADE, related_name="progress_updates")
    previous_percentage = models.PositiveSmallIntegerField()
    new_percentage = models.PositiveSmallIntegerField(validators=[MinValueValidator(0), MaxValueValidator(100)])
    update_note = models.TextField(blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"{self.previous_percentage}% -> {self.new_percentage}%"
