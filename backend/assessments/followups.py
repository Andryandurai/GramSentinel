"""Follow-up urgency, in one place.

The platform already stores the two facts that matter — `FollowUp.due_date` and
`FollowUp.status` — so this module only derives a display state from them. It
does not introduce a second, competing notion of "overdue": a follow-up is
overdue because its recorded due date has passed, and completed because the
worker marked it completed.

Priority, highest first:

    OVERDUE   ->  DUE TODAY  ->  EARLIEST UPCOMING  ->  LATER UPCOMING

which is exactly ascending due date, so the ordering comes straight from the
stored dates rather than from a hand-written list. Ties are broken by patient
name and then by id, so the same data always produces the same order.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .models import FollowUp

OVERDUE = "OVERDUE"
DUE_TODAY = "DUE_TODAY"
UPCOMING = "UPCOMING"
COMPLETED = "COMPLETED"
MISSED = "MISSED"
UNSCHEDULED = "UNSCHEDULED"

STATUS_LABELS = {
    OVERDUE: "Overdue",
    DUE_TODAY: "Due today",
    UPCOMING: "Upcoming",
    COMPLETED: "Completed",
    MISSED: "Missed",
    UNSCHEDULED: "No date recorded",
}

#: Sort weight for the display state. Only used as a secondary safeguard —
#: ascending due date already produces this order for pending follow-ups.
STATUS_PRIORITY = {
    OVERDUE: 0,
    MISSED: 1,
    DUE_TODAY: 2,
    UPCOMING: 3,
    UNSCHEDULED: 4,
    COMPLETED: 5,
}


def resolve_status(
    due_date: dt.date | None, record_status: str | None, today: dt.date
) -> str:
    """Display state for one follow-up.

    A stored status of completed or missed always wins: those are decisions a
    human recorded, and a date cannot override them.
    """

    if record_status == FollowUp.Status.COMPLETED:
        return COMPLETED
    if record_status == FollowUp.Status.MISSED:
        return MISSED
    if not isinstance(due_date, dt.date):
        return UNSCHEDULED
    if due_date < today:
        return OVERDUE
    if due_date == today:
        return DUE_TODAY
    return UPCOMING


def days_until(due_date: dt.date | None, today: dt.date) -> int | None:
    if not isinstance(due_date, dt.date):
        return None
    return (due_date - today).days


def due_description(due_date: dt.date | None, today: dt.date) -> str:
    """'Due today', 'Overdue by 3 days', 'Due in 5 days' — never a bare number."""

    delta = days_until(due_date, today)
    if delta is None:
        return "No follow-up date recorded"
    if delta == 0:
        return "Due today"
    if delta < 0:
        overdue_by = abs(delta)
        return f"Overdue by {overdue_by} day{'s' if overdue_by != 1 else ''}"
    if delta == 1:
        return "Due tomorrow"
    return f"Due in {delta} days"


def order_queryset(queryset):
    """Earliest due date first, then a stable secondary ordering."""

    return queryset.order_by("due_date", "patient__display_name", "patient_id", "id")


def sort_key(followup: FollowUp, today: dt.date) -> tuple[Any, ...]:
    """Ordering key for a list already loaded into memory."""

    status = resolve_status(followup.due_date, followup.status, today)
    return (
        STATUS_PRIORITY.get(status, 9),
        followup.due_date or dt.date.max,
        (getattr(followup.patient, "display_name", "") or "").lower(),
        followup.id or 0,
    )
