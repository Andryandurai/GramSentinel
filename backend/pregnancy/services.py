"""Pregnancy profile / visit persistence — the one place a profile is
created, a visit is recorded, or a follow-up task is requested. Views never
write these models directly, mirroring `simulation.services.SimulationEngine`
being the one place a session progresses.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from assessments.models import FollowUp
from agents.pregnancy.orchestrator import run_pregnancy_guidance

from .models import (
    PregnancyProfile,
    PregnancyProfileEvent,
    PregnancyStatus,
    PregnancyVisitAssessment,
)
from .questionnaire import valid_question_keys
from .rules import evaluate_profile_rules, warning_signs_in_responses


class PregnancyProfileAlreadyActive(APIException):
    status_code = 409
    default_detail = "This patient already has an active pregnancy profile."
    default_code = "pregnancy_profile_already_active"


def completed_visit_count(profile: PregnancyProfile) -> int:
    return profile.visits.count()


def latest_visit(profile: PregnancyProfile) -> PregnancyVisitAssessment | None:
    return profile.visits.order_by("-visit_date", "-id").first()


def visit_history_status(profile: PregnancyProfile) -> dict:
    """The Phase 13 backend-derived summary — never computed on the
    frontend. `overdue` and every count here comes straight from the
    deterministic rules layer, not a second, competing calculation."""

    from .questionnaire import TARGET_VISIT_COUNT

    completed = completed_visit_count(profile)
    latest = latest_visit(profile)
    flags = evaluate_profile_rules(
        status=profile.status,
        next_checkup_date=profile.next_checkup_date,
        lmp=profile.lmp,
        picme_rch_status=profile.picme_rch_status,
        completed_visit_count=completed,
        latest_warning_signs=(latest.warning_signs if latest else []),
    )
    return {
        "completed_visit_count": completed,
        "target_visit_count": TARGET_VISIT_COUNT,
        "next_checkup_date": profile.next_checkup_date,
        "rule_flags": flags,
    }


@transaction.atomic
def create_pregnancy_profile(
    *, patient, village, created_by
) -> PregnancyProfile:
    # Two independent checks, same "never rely on one guard alone" shape
    # `simulation.permissions`/`simulation.services` use for village scope:
    # the DB constraint (`unique_active_pregnancy_per_patient`) is the real
    # guarantee; this pre-check exists only to fail with a clear message
    # instead of a raw IntegrityError.
    if PregnancyProfile.objects.filter(
        patient=patient, status=PregnancyStatus.ACTIVE
    ).exists():
        raise PregnancyProfileAlreadyActive()

    profile = PregnancyProfile.objects.create(
        patient=patient, village=village, created_by=created_by
    )
    PregnancyProfileEvent.objects.create(
        pregnancy_profile=profile,
        event_type=PregnancyProfileEvent.EventType.PROFILE_CREATED,
        actor=created_by,
    )
    return profile


@transaction.atomic
def update_picme(
    *, profile: PregnancyProfile, picme_rch_id: str, picme_rch_status: str, actor
) -> PregnancyProfile:
    before = {"picme_rch_id": profile.picme_rch_id, "picme_rch_status": profile.picme_rch_status}
    profile.picme_rch_id = picme_rch_id
    profile.picme_rch_status = picme_rch_status
    profile.save(update_fields=["picme_rch_id", "picme_rch_status", "updated_at"])
    PregnancyProfileEvent.objects.create(
        pregnancy_profile=profile,
        event_type=PregnancyProfileEvent.EventType.PICME_UPDATED,
        actor=actor,
        detail={"before": before, "after": {"picme_rch_id": picme_rch_id, "picme_rch_status": picme_rch_status}},
    )
    return profile


@transaction.atomic
def record_visit(
    *,
    profile: PregnancyProfile,
    visit_number: int,
    responses: dict[str, str],
    visit_date: dt.date | None,
    next_checkup_date: dt.date | None,
    lmp_from_visit: dt.date | None,
    worker,
    language: str = "en",
) -> PregnancyVisitAssessment:
    """Records one visit, evaluates the deterministic rules against the
    resulting state, and asks the (optional, always-falls-back) AI guidance
    agent to explain it. The rules are evaluated first and passed to the
    agent — it narrates a decision already made, never makes one."""

    valid_keys = valid_question_keys(visit_number)
    clean_responses = {k: v for k, v in responses.items() if k in valid_keys}
    warning_signs = warning_signs_in_responses(visit_number, clean_responses)

    visit_date = visit_date or timezone.localdate()

    visit = PregnancyVisitAssessment.objects.create(
        pregnancy_profile=profile,
        visit_number=visit_number,
        visit_date=visit_date,
        questionnaire_responses=clean_responses,
        next_checkup_date=next_checkup_date,
        warning_signs=warning_signs,
        worker=worker,
    )

    # LMP is only ever set here if the profile does not already have one —
    # never silently overwritten (task §2: "if unknown, store NULL; do not
    # convert missing dates to fake values" — the same principle extends to
    # not clobbering an already-known value with a later, possibly-recalled
    # one).
    update_fields = ["updated_at"]
    if lmp_from_visit is not None and profile.lmp is None:
        profile.lmp = lmp_from_visit
        update_fields.append("lmp")
    if next_checkup_date is not None:
        profile.next_checkup_date = next_checkup_date
        update_fields.append("next_checkup_date")
    if len(update_fields) > 1:
        profile.save(update_fields=update_fields)
        if "next_checkup_date" in update_fields:
            PregnancyProfileEvent.objects.create(
                pregnancy_profile=profile,
                event_type=PregnancyProfileEvent.EventType.NEXT_CHECKUP_CHANGED,
                actor=worker,
                detail={"next_checkup_date": next_checkup_date.isoformat()},
            )

    completed = completed_visit_count(profile)
    rule_flags = evaluate_profile_rules(
        status=profile.status,
        next_checkup_date=profile.next_checkup_date,
        lmp=profile.lmp,
        picme_rch_status=profile.picme_rch_status,
        completed_visit_count=completed,
        latest_warning_signs=warning_signs,
    )

    guidance_result = run_pregnancy_guidance(
        {
            "visit_number": visit_number,
            "warning_signs": warning_signs,
            "rule_flags": rule_flags,
            "next_checkup_date": (
                profile.next_checkup_date.isoformat() if profile.next_checkup_date else None
            ),
            "picme_rch_status": profile.picme_rch_status,
            "completed_visit_count": completed,
            "language": language,
        },
        village_code=profile.village.code,
    )

    visit.rule_flags = rule_flags
    visit.ai_guidance = guidance_result.get("guidance", {})
    visit.llm_used = bool(guidance_result.get("used_llm"))
    visit.save(update_fields=["rule_flags", "ai_guidance", "llm_used"])

    PregnancyProfileEvent.objects.create(
        pregnancy_profile=profile,
        event_type=PregnancyProfileEvent.EventType.VISIT_RECORDED,
        actor=worker,
        detail={"visit_id": visit.id, "visit_number": visit_number, "warning_signs": warning_signs},
    )

    return visit


@transaction.atomic
def change_status(*, profile: PregnancyProfile, status: str, actor) -> PregnancyProfile:
    before = profile.status
    profile.status = status
    profile.save(update_fields=["status", "updated_at"])
    PregnancyProfileEvent.objects.create(
        pregnancy_profile=profile,
        event_type=PregnancyProfileEvent.EventType.STATUS_CHANGED,
        actor=actor,
        detail={"before": before, "after": status},
    )
    return profile


@transaction.atomic
def request_followup(
    *, profile: PregnancyProfile, officer, priority: str, due_date: dt.date, reason: str
) -> FollowUp:
    """Reuses `assessments.FollowUp` — the existing, already worker-visible
    follow-up/task infrastructure (task §18/§27: "do not create duplicate
    task infrastructure"). A worker in this pregnancy's village sees it the
    same way they already see every other pending follow-up, on their
    existing dashboard."""

    followup = FollowUp.objects.create(
        patient=profile.patient,
        due_date=due_date,
        notes=reason or "Pregnancy follow-up required - household visit requested by health officer.",
        priority=priority,
        created_by=officer,
    )
    PregnancyProfileEvent.objects.create(
        pregnancy_profile=profile,
        event_type=PregnancyProfileEvent.EventType.FOLLOWUP_TASK_CREATED,
        actor=officer,
        detail={"followup_id": followup.id, "due_date": due_date.isoformat(), "priority": priority},
    )
    return followup
