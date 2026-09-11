"""Worker-facing endpoints: assess a patient, submit, track follow-ups.

Two entry points into the same agent chain:

  POST /api/assessments/preview/  run the agents, return support, store nothing
  POST /api/assessments/          run the agents, store the encounter, and
                                  refresh this village's anonymised aggregate

The preview exists because the worker should see the suggestion, apply their
own judgement, and only then decide to record the encounter.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from agents.orchestration import RuralCareOrchestrator
from community.aggregation import aggregate_village_week, week_label_for
from config.exceptions import AgentFailure
from core.constants import DATA_NOTICE, MEDICAL_DISCLAIMER
from patients.models import Patient
from users.permissions import IsWorker

from . import followups as followup_rules
from .models import FollowUp, PatientAssessment
from .serializers import (
    AssessmentInputSerializer,
    FollowUpSerializer,
    PatientAssessmentSerializer,
)
from .symptom_summary import summarise_assessments
from .weeks import (
    ALL_WEEKS,
    build_week_options,
    format_range,
    resolve_selection,
)

#: How many pending follow-ups the dashboard card carries. Generous enough that
#: the demonstration data never reaches it; the exact count is reported
#: separately so the card can say so if it ever does.
MAX_DASHBOARD_FOLLOWUPS = 60


def _resolve_patient(request, patient_id: int) -> Patient:
    queryset = Patient.objects.select_related("village")
    if request.user.village_id:
        queryset = queryset.filter(village_id=request.user.village_id)
    return generics.get_object_or_404(queryset, pk=patient_id)


def _run_agents(patient: Patient, data: dict) -> dict:
    orchestrator = RuralCareOrchestrator()
    result = orchestrator.run(
        {
            "symptoms": data.get("symptoms", []),
            "raw_symptom_text": data.get("raw_symptom_text", ""),
            # Optional extra detail. The listener keeps these as supplementary
            # context; nothing downstream turns them into symptom codes.
            "other_symptom_text": data.get("other_symptom_text", ""),
            "symptom_timeline": data.get("symptom_timeline", []),
            "duration_days": data.get("duration_days", 0),
            "temperature_c": data.get("temperature_c"),
            "pulse_bpm": data.get("pulse_bpm"),
            "respiratory_rate": data.get("respiratory_rate"),
            "systolic_bp": data.get("systolic_bp"),
            "diastolic_bp": data.get("diastolic_bp"),
            "spo2": data.get("spo2"),
            "history": data.get("history", []),
            "age_months": patient.age_in_months,
            "village_code": patient.village.code,
            "cluster": patient.village.cluster,
        }
    )
    if not result.get("ok"):
        raise AgentFailure(result.get("error", "RuralCare agent chain failed."))
    return result


def _support_payload(result: dict) -> dict:
    return {
        "triage_level": result["triage_level"],
        "model_triage_level": result["model_triage_level"],
        "triage_score": result["triage_score"],
        "contributing_factors": result["contributing_factors"],
        "reasoning_summary": result["reasoning_summary"],
        "referral_recommendation": result["referral_recommendation"],
        "referral_pathway": result["referral_pathway"],
        "followup_interval_days": result["followup_interval_days"],
        "red_flags": result["red_flags"],
        "escalation_forced": result["escalation_forced"],
        "safety_status": result["safety_status"],
        "safety_note": result["safety_note"],
        "safety_result": result["safety_result"],
        "normalised_symptoms": result["normalised_symptoms"],
        "syndrome_groups": result["syndrome_groups"],
        "completeness": result["completeness"],
        "supplementary_context": result.get("supplementary_context", {}),
        "signal_category": result["signal_category"],
        "llm_used": result["used_llm"],
        "agent_trace": result["agent_trace"],
        "flow": result["flow"],
        "disclaimer": MEDICAL_DISCLAIMER,
        "data_notice": DATA_NOTICE,
    }


class AssessmentPreviewView(APIView):
    """Run the five-agent chain without recording anything."""

    permission_classes = (IsWorker,)

    def post(self, request):
        serializer = AssessmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = _resolve_patient(request, data["patient"])
        result = _run_agents(patient, data)

        return Response(
            {
                "preview": True,
                "patient": {
                    "id": patient.id,
                    "patient_code": patient.patient_code,
                    "display_name": patient.display_name,
                },
                "support": _support_payload(result),
            }
        )


class AssessmentListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsWorker,)
    serializer_class = PatientAssessmentSerializer

    def get_queryset(self):
        queryset = PatientAssessment.objects.filter(is_draft=False).select_related(
            "patient", "village", "worker"
        )
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        if self.request.query_params.get("today") == "1":
            queryset = queryset.filter(encounter_date=timezone.localdate())
        return queryset.order_by("-created_at")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = AssessmentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        patient = _resolve_patient(request, data["patient"])
        result = _run_agents(patient, data)

        encounter_date: dt.date = data.get("encounter_date") or timezone.localdate()

        assessment = PatientAssessment.objects.create(
            patient=patient,
            worker=request.user,
            village=patient.village,
            symptoms=result["normalised_symptoms"],
            raw_symptom_text=data.get("raw_symptom_text", ""),
            other_symptom_text=data.get("other_symptom_text", ""),
            duration_days=data.get("duration_days", 0),
            symptom_timeline=data.get("symptom_timeline", []),
            temperature_c=data.get("temperature_c"),
            pulse_bpm=data.get("pulse_bpm"),
            respiratory_rate=data.get("respiratory_rate"),
            systolic_bp=data.get("systolic_bp"),
            diastolic_bp=data.get("diastolic_bp"),
            spo2=data.get("spo2"),
            history=data.get("history", []),
            notes=data.get("notes", ""),
            primary_category=result["signal_category"],
            triage_level=result["triage_level"],
            triage_score=result["triage_score"],
            reasoning_summary=result["reasoning_summary"],
            referral_recommendation=result["referral_recommendation"],
            followup_interval_days=result["followup_interval_days"],
            red_flags=result["red_flags"],
            escalation_forced=result["escalation_forced"],
            safety_status=result["safety_status"],
            agent_trace=result["agent_trace"],
            llm_used=result["used_llm"],
            is_draft=False,
            encounter_date=encounter_date,
        )

        if result["followup_interval_days"]:
            FollowUp.objects.create(
                patient=patient,
                assessment=assessment,
                due_date=encounter_date
                + dt.timedelta(days=result["followup_interval_days"]),
                created_by=request.user,
                notes="Auto-scheduled from referral suggestion.",
            )

        # The privacy boundary: only an anonymised count crosses from here.
        signals = aggregate_village_week(patient.village, encounter_date)

        return Response(
            {
                "assessment": PatientAssessmentSerializer(assessment).data,
                "support": _support_payload(result),
                "aggregation": {
                    "message": (
                        "This encounter now contributes to the community signal "
                        "only as an anonymised count."
                    ),
                    "village_code": patient.village.code,
                    "week_label": week_label_for(encounter_date),
                    "signals_written": [
                        {
                            "category": s.category,
                            "encounter_count": s.value,
                            "baseline": s.baseline,
                        }
                        for s in signals
                    ],
                },
            },
            status=status.HTTP_201_CREATED,
        )


class AssessmentDetailView(generics.RetrieveAPIView):
    permission_classes = (IsWorker,)
    serializer_class = PatientAssessmentSerializer

    def get_queryset(self):
        queryset = PatientAssessment.objects.select_related(
            "patient", "village", "worker"
        )
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        return queryset


class AssessmentTraceView(APIView):
    """The recorded agent handoffs for one stored assessment."""

    permission_classes = (IsWorker,)

    def get(self, request, pk: int):
        queryset = PatientAssessment.objects.all()
        if request.user.village_id:
            queryset = queryset.filter(village_id=request.user.village_id)
        assessment = generics.get_object_or_404(queryset, pk=pk)
        return Response(
            {
                "assessment_id": assessment.id,
                "agent_trace": assessment.agent_trace,
                "flow": [
                    f"{entry['stage']} -> {entry['agent']}"
                    for entry in assessment.agent_trace
                ],
            }
        )


class FollowUpListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsWorker,)
    serializer_class = FollowUpSerializer

    def get_queryset(self):
        queryset = FollowUp.objects.select_related("patient")
        if self.request.user.village_id:
            queryset = queryset.filter(patient__village_id=self.request.user.village_id)
        if self.request.query_params.get("pending") == "1":
            queryset = queryset.filter(status=FollowUp.Status.PENDING)

        # Optional narrowing to one patient. The village scope above is applied
        # first, so an id from another area simply matches nothing.
        patient = (self.request.query_params.get("patient") or "").strip()
        if patient.isdigit():
            queryset = queryset.filter(patient_id=int(patient))

        # Earliest due date first: overdue, then due today, then upcoming.
        return followup_rules.order_queryset(queryset)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class FollowUpDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsWorker,)
    serializer_class = FollowUpSerializer

    def get_queryset(self):
        queryset = FollowUp.objects.select_related("patient")
        if self.request.user.village_id:
            queryset = queryset.filter(patient__village_id=self.request.user.village_id)
        return queryset


class WorkerDashboardView(APIView):
    """The worker's own dashboard, optionally narrowed to one reporting week.

    `?week=` accepts a stored week label ("2026-W33"), the displayed week
    number ("2"), or "all" (the default, and what the dashboard has always
    shown). The village scope is applied **first**, so the week options and
    every filtered figure below are derived from data this worker was already
    permitted to see — narrowing a time period can never widen access.
    """

    permission_classes = (IsWorker,)

    def get(self, request):
        today = timezone.localdate()
        village = request.user.village

        assessments = PatientAssessment.objects.filter(is_draft=False)
        followups = FollowUp.objects.filter(status=FollowUp.Status.PENDING)
        if village:
            assessments = assessments.filter(village=village)
            followups = followups.filter(patient__village=village)

        week_options = build_week_options(
            [
                *assessments.values_list("encounter_date", flat=True),
                *followups.values_list("due_date", flat=True),
            ]
        )
        selected, start, end, _option, notice = resolve_selection(
            request.query_params.get("week"), week_options
        )
        is_all_weeks = selected == ALL_WEEKS

        # The week filter narrows the already-scoped querysets. Everything
        # below this point derives from these two, so a card cannot silently
        # keep showing another period's numbers.
        period_assessments = assessments
        period_followups = followups
        if not is_all_weeks:
            period_assessments = assessments.filter(
                encounter_date__gte=start, encounter_date__lte=end
            )
            period_followups = followups.filter(
                due_date__gte=start, due_date__lte=end
            )

        today_assessments = assessments.filter(encounter_date=today)
        recent = period_assessments.select_related("patient", "village").order_by(
            "-created_at"
        )[:8]

        period_count = period_assessments.count()
        period_followup_count = period_followups.count()

        # Reported-symptom counts for exactly the rows above: village scope has
        # already been applied, then the week. Only the three fields the
        # summary needs are read — no patient identifiers are aggregated.
        symptom_summary = summarise_assessments(
            period_assessments.values_list(
                "patient_id", "symptoms", "other_symptom_text"
            )
        )

        ordered_followups = list(
            followup_rules.order_queryset(
                period_followups.select_related("patient")
            )[:MAX_DASHBOARD_FOLLOWUPS]
        )
        followup_payload = FollowUpSerializer(
            ordered_followups, many=True, context={"today": today}
        ).data

        return Response(
            {
                "worker": request.user.display_name,
                "village": (
                    {
                        "code": village.code,
                        "name": village.name,
                        "cluster": village.cluster,
                    }
                    if village
                    else None
                ),
                # Unchanged: "today" is a fixed day, not a filtered period.
                "today": {
                    "date": today,
                    "assessment_count": today_assessments.count(),
                    "urgent_count": today_assessments.filter(
                        triage_level="URGENT"
                    ).count(),
                    "concerning_count": today_assessments.filter(
                        triage_level="CONCERNING"
                    ).count(),
                },
                "weeks": [
                    {
                        **option,
                        "is_current_week": option["start"]
                        <= today
                        <= option["end"],
                    }
                    for option in week_options
                ],
                "selected_week": selected,
                "period": {
                    "is_all_weeks": is_all_weeks,
                    "label": self._period_label(selected, week_options),
                    "range_label": self._range_label(
                        is_all_weeks, start, end, week_options
                    ),
                    "start": start,
                    "end": end,
                    "assessment_count": period_count,
                    "urgent_count": period_assessments.filter(
                        triage_level="URGENT"
                    ).count(),
                    "concerning_count": period_assessments.filter(
                        triage_level="CONCERNING"
                    ).count(),
                    "followup_count": period_followup_count,
                    "has_activity": bool(period_count or period_followup_count),
                    "empty_message": (
                        ""
                        if (period_count or period_followup_count or is_all_weeks)
                        else "No activity recorded for this week."
                    ),
                    "notice": notice,
                },
                # Priority order: overdue first, then due today, then the
                # earliest upcoming date. Derived from the stored due dates.
                "pending_followups": followup_payload,
                "pending_followup_count": period_followup_count,
                "followup_summary": self._followup_summary(
                    followup_payload,
                    period_followup_count,
                    followups,
                    today,
                    is_all_weeks,
                ),
                "symptom_summary": {
                    **symptom_summary,
                    "period_label": self._period_label(selected, week_options),
                    "is_all_weeks": is_all_weeks,
                    "village_name": village.name if village else "",
                },
                "recent_assessments": PatientAssessmentSerializer(
                    recent, many=True
                ).data,
                "disclaimer": MEDICAL_DISCLAIMER,
                "data_notice": DATA_NOTICE,
            }
        )

    @staticmethod
    def _followup_summary(
        rows: list[dict],
        period_total: int,
        all_pending,
        today: dt.date,
        is_all_weeks: bool,
    ) -> dict:
        """Counts, patient options and the empty/overflow states for the card.

        The patient list is built from the follow-ups already on screen, so the
        dropdown can never offer someone this worker is not permitted to see.
        """

        counts = {
            followup_rules.OVERDUE: 0,
            followup_rules.DUE_TODAY: 0,
            followup_rules.UPCOMING: 0,
            followup_rules.UNSCHEDULED: 0,
        }
        patients: dict[int, dict] = {}

        for row in rows:
            state = row.get("followup_status") or followup_rules.UPCOMING
            counts[state] = counts.get(state, 0) + 1

            patient_id = row.get("patient")
            if patient_id is None:
                continue
            entry = patients.setdefault(
                patient_id,
                {
                    "id": patient_id,
                    "patient_code": row.get("patient_code") or "",
                    "patient_name": row.get("patient_name") or "",
                    "pending_count": 0,
                    "next_due_date": row.get("due_date"),
                    "next_status": state,
                },
            )
            entry["pending_count"] += 1

        # Pending follow-ups that are already overdue but fall outside the
        # selected week. Never hidden silently — the card says so.
        overdue_outside = 0
        if not is_all_weeks:
            overdue_ids = {
                row.get("id") for row in rows
                if row.get("followup_status") == followup_rules.OVERDUE
            }
            overdue_outside = (
                all_pending.filter(due_date__lt=today)
                .exclude(id__in=[i for i in overdue_ids if i is not None])
                .count()
            )

        return {
            "counts": {
                "total": period_total,
                "shown": len(rows),
                "overdue": counts.get(followup_rules.OVERDUE, 0),
                "due_today": counts.get(followup_rules.DUE_TODAY, 0),
                "upcoming": counts.get(followup_rules.UPCOMING, 0),
                "undated": counts.get(followup_rules.UNSCHEDULED, 0),
            },
            "patients": sorted(
                patients.values(),
                key=lambda p: (p["patient_name"] or "", p["patient_code"] or ""),
            ),
            "overdue_outside_period": overdue_outside,
            "overdue_outside_message": (
                f"{overdue_outside} overdue follow-up(s) fall outside this week. "
                "Select “All weeks” to see them."
                if overdue_outside
                else ""
            ),
            "empty_message": (
                "No pending follow-ups."
                if is_all_weeks
                else "No follow-ups due in this week."
            ),
            "truncated": period_total > len(rows),
            "truncated_message": (
                f"Showing the {len(rows)} most urgent of {period_total} "
                "pending follow-ups."
                if period_total > len(rows)
                else ""
            ),
        }

    @staticmethod
    def _period_label(selected: str, options: list[dict]) -> str:
        if selected == ALL_WEEKS:
            return "All weeks"
        for option in options:
            if option["value"] == selected:
                return option["label"]
        # A valid week outside this worker's own data range.
        return selected

    @staticmethod
    def _range_label(is_all_weeks, start, end, options: list[dict]) -> str:
        if not is_all_weeks and start and end:
            return format_range(start, end)
        if options:
            return format_range(options[0]["start"], options[-1]["end"])
        return ""
