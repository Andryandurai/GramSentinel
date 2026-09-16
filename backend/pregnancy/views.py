"""Pregnancy / Maternal Health follow-up — Health Worker + Health Officer
endpoints. Worker-side resolves a patient the same way `assessments.views
._resolve_patient` already does (village-scoped via the patient's own
village); officer-side uses `scope_queryset` from `users.scoping`, the same
"404, not 403" convention `alerts.views.officer_alert_queryset` established.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from patients.models import Patient
from users.models import User
from users.permissions import IsHealthOfficer, IsWorker
from users.scoping import scope_queryset, scoped_village_id

from . import services
from .models import PregnancyProfile, PregnancyStatus
from .questionnaire import VISIT_LABELS, questions_for_visit
from .rules import (
    ANC_4PLUS_TARGET_NOT_YET_REACHED,
    FOLLOW_UP_OVERDUE,
    LOW_VISIT_COMPLETION_FOR_STAGE,
    MISSING_PICME,
    URGENT_CLINICAL_REVIEW,
)
from .serializers import (
    OfficerPregnancyListItemSerializer,
    PregnancyCommunityReportDetailSerializer,
    PregnancyCommunityReportInputSerializer,
    PregnancyProfileSerializer,
    PregnancyProfileUpdateSerializer,
    RequestFollowUpInputSerializer,
    VisitInputSerializer,
)


def _resolve_patient(request, patient_id: int) -> Patient:
    """Identical scoping rule to `assessments.views._resolve_patient` — a
    worker only ever resolves a patient in their own village."""

    queryset = Patient.objects.select_related("village")
    if request.user.village_id:
        queryset = queryset.filter(village_id=request.user.village_id)
    return generics.get_object_or_404(queryset, pk=patient_id)


def _worker_profile_queryset():
    return PregnancyProfile.objects.select_related("patient", "village", "assigned_health_worker").prefetch_related("visits")


class PregnancyQuestionsView(APIView):
    """GET /api/pregnancy/questions/<visit_number>/ — the single source of
    truth for a visit's question set, so the frontend never hardcodes a
    second copy (task §1/§3: a controlled, server-defined set)."""

    permission_classes = (IsWorker,)

    def get(self, request, visit_number: int):
        if visit_number not in (1, 2, 3, 4):
            return Response({"detail": "Invalid visit number."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "visit_number": visit_number,
                "visit_label": VISIT_LABELS[visit_number],
                "questions": questions_for_visit(visit_number),
            }
        )


class PregnancyProfileListCreateView(generics.ListCreateAPIView):
    """GET ?patient=<id> — that patient's pregnancy history (village-scoped
    via the patient, never a raw id lookup). POST — start a new profile."""

    permission_classes = (IsWorker,)
    serializer_class = PregnancyProfileSerializer

    def get_queryset(self):
        patient_id = self.request.query_params.get("patient")
        queryset = _worker_profile_queryset()
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        if patient_id and patient_id.isdigit():
            queryset = queryset.filter(patient_id=int(patient_id))
        return queryset.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        patient_id = request.data.get("patient")
        if not patient_id:
            return Response({"patient": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)
        patient = _resolve_patient(request, patient_id)
        profile = services.create_pregnancy_profile(
            patient=patient, village=patient.village, created_by=request.user
        )
        return Response(PregnancyProfileSerializer(profile).data, status=status.HTTP_201_CREATED)


class PregnancyProfileDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsWorker,)
    serializer_class = PregnancyProfileSerializer

    def get_queryset(self):
        queryset = _worker_profile_queryset()
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        return queryset

    def update(self, request, *args, **kwargs):
        profile = self.get_object()
        serializer = PregnancyProfileUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "picme_rch_id" in data or "picme_rch_status" in data:
            services.update_picme(
                profile=profile,
                picme_rch_id=data.get("picme_rch_id", profile.picme_rch_id),
                picme_rch_status=data.get("picme_rch_status", profile.picme_rch_status),
                actor=request.user,
            )
        if "next_checkup_date" in data:
            profile.next_checkup_date = data["next_checkup_date"]
        if "expected_delivery_date" in data:
            profile.expected_delivery_date = data["expected_delivery_date"]
        if "assigned_health_worker" in data:
            worker_id = data["assigned_health_worker"]
            if worker_id is None:
                profile.assigned_health_worker_id = None
            else:
                worker_queryset = User.objects.filter(role=User.Role.CHW_PHC_WORKER)
                if profile.village_id:
                    worker_queryset = worker_queryset.filter(village_id=profile.village_id)
                worker = generics.get_object_or_404(worker_queryset, pk=worker_id)
                profile.assigned_health_worker_id = worker.id
        if "status" in data and data["status"] != profile.status:
            services.change_status(profile=profile, status=data["status"], actor=request.user)
        profile.save()

        profile.refresh_from_db()
        return Response(PregnancyProfileSerializer(profile).data)


class PregnancyVisitCreateView(APIView):
    """POST /api/pregnancy/profiles/<id>/visits/ — record one pregnancy
    visit: the questionnaire responses, next check-up date, and optionally
    the PICME/RCH ID/status, all in the one save the Phase 36 manual flow
    describes ("Complete questionnaire -> Enter PICME/RCH ID -> Set next
    check-up -> Save")."""

    permission_classes = (IsWorker,)

    def post(self, request, pk: int):
        queryset = _worker_profile_queryset()
        if request.user.village_id:
            queryset = queryset.filter(village_id=request.user.village_id)
        profile = generics.get_object_or_404(queryset, pk=pk)

        serializer = VisitInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "picme_rch_id" in data or "picme_rch_status" in data:
            services.update_picme(
                profile=profile,
                picme_rch_id=data.get("picme_rch_id", profile.picme_rch_id),
                picme_rch_status=data.get("picme_rch_status", profile.picme_rch_status),
                actor=request.user,
            )
            profile.refresh_from_db()

        visit = services.record_visit(
            profile=profile,
            visit_number=int(data["visit_number"]),
            responses=data["responses"],
            visit_date=data.get("visit_date"),
            next_checkup_date=data.get("next_checkup_date"),
            lmp_from_visit=data.get("lmp_from_visit"),
            worker=request.user,
            language=data.get("language", "en"),
        )
        profile.refresh_from_db()

        return Response(
            {
                "profile": PregnancyProfileSerializer(profile).data,
                "visit": {
                    "id": visit.id,
                    "visit_number": visit.visit_number,
                    "warning_signs": visit.warning_signs,
                    "rule_flags": visit.rule_flags,
                    "ai_guidance": visit.ai_guidance,
                    "llm_used": visit.llm_used,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class PregnancyCommunityReportCreateView(APIView):
    """POST /api/pregnancy/community-reports/ — the Pregnancy option inside
    Community Report. The worker only names which pregnancy and why; the
    village-scoped resolution and every derived field come from
    `pregnancy.services.create_pregnancy_community_report`. Submits into the
    same `community.CommunityReport` table and lifecycle the General report
    already uses — an officer sees it on the same Community Reports list,
    just tagged `report_type=PREGNANCY`.
    """

    permission_classes = (IsWorker,)

    def post(self, request):
        serializer = PregnancyCommunityReportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        queryset = _worker_profile_queryset()
        if request.user.village_id:
            queryset = queryset.filter(village_id=request.user.village_id)
        profile = generics.get_object_or_404(queryset, pk=data["pregnancy_profile"])

        community_report, detail = services.create_pregnancy_community_report(
            profile=profile,
            worker=request.user,
            reason=data["reason"],
            remarks=data["remarks"],
        )

        return Response(
            {
                "id": community_report.id,
                "report_type": community_report.report_type,
                "village_name": community_report.village.name,
                "week_label": community_report.week_label,
                "submitted_at": community_report.submitted_at,
                "pregnancy_detail": PregnancyCommunityReportDetailSerializer(detail).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WorkerPregnancySummaryView(APIView):
    """GET /api/pregnancy/worker/summary/ — the compact Phase 14 dashboard
    card. Village-scoped exactly like every other card on that dashboard."""

    permission_classes = (IsWorker,)

    def get(self, request):
        queryset = PregnancyProfile.objects.filter(status=PregnancyStatus.ACTIVE)
        if request.user.village_id:
            queryset = queryset.filter(village_id=request.user.village_id)

        today = timezone.localdate()
        active = list(queryset.prefetch_related("visits"))
        due_soon = 0
        overdue = 0
        missing_picme = 0
        for profile in active:
            status_data = services.visit_history_status(profile)
            flags = {f["rule"] for f in status_data["rule_flags"]}
            if FOLLOW_UP_OVERDUE in flags:
                overdue += 1
            elif profile.next_checkup_date and 0 <= (profile.next_checkup_date - today).days <= 7:
                due_soon += 1
            if MISSING_PICME in flags:
                missing_picme += 1

        return Response(
            {
                "active_pregnancies": len(active),
                "due_soon": due_soon,
                "overdue": overdue,
                "missing_picme": missing_picme,
            }
        )


def _officer_profile_queryset(user):
    return scope_queryset(
        PregnancyProfile.objects.select_related("patient", "village", "assigned_health_worker").prefetch_related("visits"),
        user,
    )


class OfficerPregnancySummaryView(APIView):
    """GET /api/pregnancy/officer/summary/ — Phase 15 dashboard card.
    Aggregate counts only — no individual patient identifiers, per task
    §15/§19."""

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        queryset = _officer_profile_queryset(request.user).filter(status=PregnancyStatus.ACTIVE)
        active = list(queryset)

        total_visits = 0
        due = 0
        overdue = 0
        below_target = 0
        picme_pending = 0
        for profile in active:
            status_data = services.visit_history_status(profile)
            total_visits += status_data["completed_visit_count"]
            flags = {f["rule"] for f in status_data["rule_flags"]}
            if FOLLOW_UP_OVERDUE in flags or URGENT_CLINICAL_REVIEW in flags:
                overdue += 1
            elif profile.next_checkup_date:
                due += 1
            # Task §17: never "fewer than 4 visits" alone — only the
            # deterministic rules layer's own stage-aware flags count here,
            # the exact same flags the officer list filters on.
            if flags & {LOW_VISIT_COMPLETION_FOR_STAGE, ANC_4PLUS_TARGET_NOT_YET_REACHED}:
                below_target += 1
            if MISSING_PICME in flags:
                picme_pending += 1

        return Response(
            {
                "active_pregnancies": len(active),
                "completed_anc_visits": total_visits,
                "due_followups": due,
                "overdue_followups": overdue,
                "below_visit_target": below_target,
                "picme_registration_pending": picme_pending,
                "scope": {
                    "village_code": request.user.village.code if request.user.village else None,
                    "is_district_wide": scoped_village_id(request.user) is None,
                },
            }
        )


class OfficerPregnancyListView(generics.ListAPIView):
    """GET /api/pregnancy/officer/list/ — Phase 16 detailed list.
    `?follow_up_required=1` narrows to profiles the deterministic rules
    layer actually flagged as overdue/urgent — never "fewer than 4 visits"
    alone (task §17)."""

    permission_classes = (IsHealthOfficer,)
    serializer_class = OfficerPregnancyListItemSerializer

    def get_queryset(self):
        queryset = _officer_profile_queryset(self.request.user).order_by("-created_at")
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        rows = serializer.data
        if request.query_params.get("follow_up_required") == "1":
            rows = [
                row for row in rows
                if any(
                    f["rule"] in {FOLLOW_UP_OVERDUE, URGENT_CLINICAL_REVIEW}
                    for f in row["visit_status"]["rule_flags"]
                )
            ]
        return Response(rows)


class OfficerRequestFollowUpView(APIView):
    """POST /api/pregnancy/officer/profiles/<id>/request-followup/ — Phase
    18: reuses `assessments.FollowUp` via `pregnancy.services
    .request_followup`, never a second task system."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        queryset = _officer_profile_queryset(request.user)
        profile = generics.get_object_or_404(queryset, pk=pk)

        serializer = RequestFollowUpInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        reason = data.get("reason") or "Pregnancy follow-up required - household visit requested by health officer."
        followup = services.request_followup(
            profile=profile,
            officer=request.user,
            priority=data["priority"],
            due_date=data["due_date"],
            reason=reason,
        )
        return Response(
            {
                "followup_id": followup.id,
                "due_date": followup.due_date,
                "priority": followup.priority,
                "notes": followup.notes,
            },
            status=status.HTTP_201_CREATED,
        )
