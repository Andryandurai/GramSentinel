"""Server-derived relationships and record access for Work & Communication.

Every function here exists to make one thing structurally true: a worker
can never choose their supervisor, another worker's data, or another
village's data by supplying an id. The client never gets to name an
officer, a worker, or a village — every lookup below starts from
`request.user` and follows a real database relationship from there.
"""

from __future__ import annotations

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist

from users.models import User

from .models import CORRECTABLE_MODELS, OFFICER_ALLOWED_TRANSITIONS, WorkflowStatus


class NoAssignedOfficer(Exception):
    """Raised when a worker's village has no active Health Officer to
    message — a data-completeness problem, not a permission problem."""


def assigned_officer_for(worker: User) -> User:
    """The one Health Officer a worker may communicate with — derived
    entirely server-side from `worker.village`. Never accepts or trusts a
    client-supplied officer id anywhere in this module."""

    if worker.village_id is None:
        raise NoAssignedOfficer("Your account has no assigned area yet.")

    officer = (
        User.objects.filter(
            role=User.Role.HEALTH_OFFICER,
            village_id=worker.village_id,
            is_active=True,
        )
        .order_by("id")
        .first()
    )
    if officer is None:
        raise NoAssignedOfficer(
            "No Health Officer is currently assigned to your area."
        )
    return officer


def workers_supervised_by(officer: User):
    """Every CHW/PHC worker in the officer's own village — `None` (a
    district-wide account) intentionally returns every active worker,
    mirroring `users.scoping`'s own "no village means district-wide" rule
    rather than a second, competing definition of it."""

    queryset = User.objects.filter(role=User.Role.CHW_PHC_WORKER, is_active=True)
    if officer.village_id is not None:
        queryset = queryset.filter(village_id=officer.village_id)
    return queryset.order_by("full_name", "username")


def apply_status_transition(
    *, current_status: str, target_status: str, actor: User, is_worker_actor: bool
) -> None:
    """Raises `PermissionError` if `actor` is not allowed to move
    `current_status` -> `target_status`. Enforced identically for report
    approvals and correction requests — both use `WorkflowStatus` and this
    one function, so the two workflows can never quietly drift apart.

    The only worker-initiated transition is RETURNED_FOR_CORRECTION ->
    RESUBMITTED (a resubmission). Every other transition is the Health
    Officer's alone, and is checked against the fixed
    `OFFICER_ALLOWED_TRANSITIONS` table in models.py — never a caller-
    supplied rule.
    """

    if is_worker_actor:
        if not (
            current_status == WorkflowStatus.RETURNED_FOR_CORRECTION
            and target_status == WorkflowStatus.RESUBMITTED
        ):
            raise PermissionError(
                "Only a Health Officer can change the status of this item."
            )
        return

    allowed = OFFICER_ALLOWED_TRANSITIONS.get(current_status, ())
    if target_status not in allowed:
        raise PermissionError(
            f"'{target_status}' is not a valid next status from '{current_status}'."
        )


# ---------------------------------------------------------------------------
# Correctable records
# ---------------------------------------------------------------------------
def _correctable_content_types() -> dict[str, ContentType]:
    return {
        label: ContentType.objects.get_for_model(apps.get_model(label))
        for label in CORRECTABLE_MODELS
    }


def correctable_record_or_none(*, model_label: str, object_id: int, worker: User):
    """Returns the record if it exists, is one of the allowed correctable
    types, and genuinely belongs to `worker` — never trusts the caller's
    claim of ownership. `None` on any failure, so the view can respond with
    a uniform 404 rather than leaking which check failed."""

    if model_label not in CORRECTABLE_MODELS:
        return None
    try:
        model = apps.get_model(model_label)
        record = model.objects.select_related("worker", "village").get(pk=object_id)
    except (LookupError, ObjectDoesNotExist, ValueError):
        return None

    if getattr(record, "worker_id", None) != worker.id:
        return None
    return record


def record_report_submission(report, *, actor) -> None:
    """Called once, right after `community.CommunityReport` is written by
    its own existing submission endpoint (`community/views.py::
    CommunityReportListCreateView.create()`) — the "tiny change technically
    required" the task allows, rather than a second submission pathway.
    Never called anywhere else, and never itself computes anything about
    the report's content.

    First submission for this report row -> a new `ReportApproval` at
    SUBMITTED. A resubmission while RETURNED_FOR_CORRECTION -> RESUBMITTED
    (the task's own required transition). A resubmission in any other
    state is treated as a fresh submission of the same report identity and
    reset to SUBMITTED, so the officer is not left reviewing stale figures
    against a report that has since changed under them.
    """

    from .models import ReportApproval, ReportApprovalEvent

    approval, created = ReportApproval.objects.get_or_create(
        report=report,
        defaults={
            "village_id": report.village_id,
            "worker_id": report.worker_id,
            "status": WorkflowStatus.SUBMITTED,
        },
    )
    if created:
        ReportApprovalEvent.objects.create(
            approval=approval, from_status="", to_status=WorkflowStatus.SUBMITTED, actor=actor
        )
        return

    previous = approval.status
    target = (
        WorkflowStatus.RESUBMITTED
        if previous == WorkflowStatus.RETURNED_FOR_CORRECTION
        else WorkflowStatus.SUBMITTED
    )
    if target == previous:
        return
    approval.status = target
    approval.worker_id = report.worker_id
    approval.save(update_fields=["status", "worker", "updated_at"])
    ReportApprovalEvent.objects.create(
        approval=approval, from_status=previous, to_status=target, actor=actor
    )


def record_label_and_snapshot(record) -> tuple[str, dict[str, str]]:
    """A plain-language identifier and a small field/value snapshot for the
    two currently-correctable record types — deliberately explicit per
    type (not a generic "dump every field" reflection) so a field a patient
    might be identifiable from is never accidentally included.
    """

    model_name = record._meta.model_name
    if model_name == "patientassessment":
        label = f"Assessment #{record.pk} ({record.encounter_date:%d %b %Y})"
        snapshot = {
            "Encounter date": record.encounter_date.isoformat(),
            "Primary category": record.get_primary_category_display(),
            "Triage level": record.get_triage_level_display(),
        }
        if record.temperature_c is not None:
            snapshot["Temperature (C)"] = str(record.temperature_c)
        if record.pulse_bpm is not None:
            snapshot["Pulse (bpm)"] = str(record.pulse_bpm)
        if record.sugar_mg_dl is not None:
            snapshot["Blood sugar (mg/dL)"] = str(record.sugar_mg_dl)
        return label, snapshot

    if model_name == "communityreport":
        label = f"Community report {record.week_label} ({record.village.code})"
        snapshot = {
            "Reporting week": record.week_label,
            "Fever cases": str(record.fever_cases),
            "Respiratory cases": str(record.respiratory_cases),
            "Diarrhoeal cases": str(record.diarrhoeal_cases),
            "Other cases": str(record.other_cases),
        }
        return label, snapshot

    return f"Record #{record.pk}", {}
