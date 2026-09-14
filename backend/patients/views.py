from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response

from assessments import followups as followup_rules
from assessments.models import FollowUp
from assessments.serializers import FollowUpSerializer, PatientAssessmentSerializer
from users.permissions import IsWorker

from .models import Patient
from .serializers import (
    PatientCreateSerializer,
    PatientDetailUpdateSerializer,
    PatientSerializer,
)


class PatientListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsWorker,)

    def get_serializer_class(self):
        return (
            PatientCreateSerializer
            if self.request.method == "POST"
            else PatientSerializer
        )

    def get_queryset(self):
        queryset = (
            Patient.objects.select_related("village")
            .annotate(assessment_count=Count("assessments"))
            .order_by("patient_code")
        )
        # Workers see their own area unless they are unscoped.
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(patient_code__icontains=search)
        return queryset

    def create(self, request, *args, **kwargs):
        """Register a patient, defaulting to the worker's own village."""

        data = request.data.copy()
        if not data.get("village") and request.user.village_id:
            data["village"] = request.user.village_id

        serializer = PatientCreateSerializer(data=data)
        serializer.is_valid(raise_exception=True)

        village = serializer.validated_data["village"]
        if request.user.village_id and village.id != request.user.village_id:
            return Response(
                {"detail": "You may only register patients in your own village."},
                status=status.HTTP_403_FORBIDDEN,
            )

        patient = serializer.save(created_by=request.user)
        return Response(
            PatientSerializer(patient).data, status=status.HTTP_201_CREATED
        )


class PatientDetailView(generics.RetrieveAPIView):
    """GET returns the full patient + encounter history (below). PATCH is
    deliberately narrower: `PatientDetailUpdateSerializer` only accepts the
    four patient-detail fields (height/weight/phone/house location) — a
    worker corrects or fills these in for a patient already on file, never
    the identifier, name, age, sex or village those same protections
    (`get_object()` below, from the same village-scoped `get_queryset()`
    the GET path already uses) exist to keep stable.
    """

    permission_classes = (IsWorker,)
    serializer_class = PatientSerializer
    lookup_field = "pk"

    def get_queryset(self):
        queryset = Patient.objects.select_related("village").annotate(
            assessment_count=Count("assessments")
        )
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        return queryset

    def patch(self, request, *args, **kwargs):
        patient = self.get_object()
        serializer = PatientDetailUpdateSerializer(
            patient, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PatientSerializer(patient).data, status=status.HTTP_200_OK)

    def retrieve(self, request, *args, **kwargs):
        patient = self.get_object()
        assessments = (
            patient.assessments.filter(is_draft=False)
            .select_related("patient", "village")
            .order_by("-encounter_date", "-created_at")
        )

        # Follow-ups for this patient, most urgent first. The record is already
        # village-scoped by get_queryset, so this adds no new access — it puts
        # the follow-up detail on the page the worker already opens from the
        # dashboard, rather than duplicating it somewhere else.
        today = timezone.localdate()
        followups = sorted(
            patient.followups.select_related("patient").all(),
            key=lambda f: followup_rules.sort_key(f, today),
        )
        pending = [f for f in followups if f.status == FollowUp.Status.PENDING]

        return Response(
            {
                "patient": PatientSerializer(patient).data,
                "assessments": PatientAssessmentSerializer(assessments, many=True).data,
                "followups": FollowUpSerializer(
                    followups, many=True, context={"today": today}
                ).data,
                "followup_summary": {
                    "pending_count": len(pending),
                    "next_due_date": pending[0].due_date if pending else None,
                    "last_assessment_date": (
                        assessments[0].encounter_date if assessments else None
                    ),
                    "empty_message": "No follow-ups recorded for this patient.",
                },
            }
        )
