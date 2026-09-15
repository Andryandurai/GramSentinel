"""Server-derived access and workflow rules for Field Operations — the
same shape `workspace/services.py` already established for Work &
Communication: every relationship is derived from `request.user` and a
real database link, never trusted from a client-supplied id.
"""

from __future__ import annotations

from django.utils import timezone

from users.models import User

from .models import (
    FIELD_VISIT_TRANSITIONS,
    INSPECTION_TRANSITIONS,
    ChecklistItemTemplate,
    Inspection,
    InspectionChecklistResponse,
)


def officers_in_village(village_id: int | None):
    """Health Officers eligible to be assigned a field visit — the
    frontend's "Assigned Officer" list must only ever contain these (task:
    "Assigned officer must only contain officers authorized for the
    selected village... Do not allow assigning a worker as an officer").
    """

    queryset = User.objects.filter(role=User.Role.HEALTH_OFFICER, is_active=True)
    if village_id is not None:
        queryset = queryset.filter(village_id=village_id)
    return queryset.order_by("full_name", "username")


def staff_in_village(village_id: int | None):
    """Broader pool for Action Plan's optional "Responsible Officer" —
    Health Officers and CHW/PHC workers alike may be named responsible for
    carrying out a corrective action, unlike a field visit's own assigned
    officer, which is Health-Officer-only per the task's explicit rule."""

    queryset = User.objects.filter(
        role__in={User.Role.HEALTH_OFFICER, User.Role.CHW_PHC_WORKER}, is_active=True
    )
    if village_id is not None:
        queryset = queryset.filter(village_id=village_id)
    return queryset.order_by("full_name", "username")


def apply_transition(*, current_status: str, target_status: str, table: dict[str, tuple[str, ...]]) -> None:
    """Raises PermissionError if `target_status` is not a permitted next
    step from `current_status` in `table` — the one place either
    FieldVisit or Inspection status ever changes, so "do not allow
    arbitrary client-defined status values" is enforced structurally, not
    by convention."""

    allowed = table.get(current_status, ())
    if target_status not in allowed:
        raise PermissionError(f"'{target_status}' is not a valid next status from '{current_status}'.")


def apply_field_visit_transition(current_status: str, target_status: str) -> None:
    apply_transition(current_status=current_status, target_status=target_status, table=FIELD_VISIT_TRANSITIONS)


def apply_inspection_transition(current_status: str, target_status: str) -> None:
    apply_transition(current_status=current_status, target_status=target_status, table=INSPECTION_TRANSITIONS)


def create_inspection_responses(inspection: Inspection) -> None:
    """Auto-creates one unanswered `InspectionChecklistResponse` per active
    template item in the inspection's category — called once, right after
    an `Inspection` is created. The officer only ever updates these rows;
    nothing in this app ever lets a client create an arbitrary checklist
    response row for an item outside the inspection's own category."""

    templates = ChecklistItemTemplate.objects.filter(category=inspection.inspection_type, is_active=True)
    InspectionChecklistResponse.objects.bulk_create(
        [InspectionChecklistResponse(inspection=inspection, template_item=item) for item in templates]
    )


def checklist_summary(inspection: Inspection) -> dict[str, int]:
    """Computed from the actually-stored responses — never accepted from
    the client (task: "Do NOT allow the frontend to submit arbitrary
    summary counts")."""

    responses = list(inspection.responses.all())
    return {
        "total": len(responses),
        "passed": sum(1 for r in responses if r.status == "PASSED"),
        "failed": sum(1 for r in responses if r.status == "FAILED"),
        "needs_action": sum(1 for r in responses if r.status == "NEEDS_ACTION"),
        "not_reviewed": sum(1 for r in responses if r.status is None),
    }


def status_for_progress(progress: int) -> str:
    """0 -> Pending, 1-99 -> In progress, 100 -> Completed — the task's own
    recommended, and here the ONLY, status derivation: there is no
    independent status field an officer can set inconsistently with
    progress (task: "Do not allow Status = Completed, Progress = 45%
    unless the existing workflow explicitly supports that" — this project
    has no such existing workflow, so it does not)."""

    from .models import ActionPlanStatus

    if progress <= 0:
        return ActionPlanStatus.PENDING
    if progress >= 100:
        return ActionPlanStatus.COMPLETED
    return ActionPlanStatus.IN_PROGRESS


def mark_visit_completed_fields(visit) -> None:
    visit.completed_at = timezone.now()


def mark_inspection_completed_fields(inspection) -> None:
    inspection.completed_at = timezone.now()


def mark_action_plan_completion_fields(action_plan, *, previously_completed: bool) -> None:
    if action_plan.status == "COMPLETED" and not previously_completed:
        action_plan.completed_at = timezone.now()
    elif action_plan.status != "COMPLETED":
        action_plan.completed_at = None
