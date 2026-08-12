from django.db.models import Count
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from assessments.models import FollowUp
from assessments.serializers import PatientAssessmentSerializer
from core.constants import MEDICAL_DISCLAIMER
from users.permissions import IsPatient, IsWorker

from .models import Patient
from .serializers import (
    PatientCreateSerializer,
    PatientSerializer,
    PatientSelfAssessmentSerializer,
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

    def retrieve(self, request, *args, **kwargs):
        patient = self.get_object()
        assessments = (
            patient.assessments.filter(is_draft=False)
            .select_related("patient", "village")
            .order_by("-encounter_date", "-created_at")
        )
        return Response(
            {
                "patient": PatientSerializer(patient).data,
                "assessments": PatientAssessmentSerializer(assessments, many=True).data,
            }
        )


class PatientPortalView(APIView):
    """The optional, secondary patient portal.

    A patient sees only their own records, follow-ups and general guidance.
    Everything else is structurally out of reach: this view resolves the
    patient from `request.user.patient_profile` and never accepts an id, so
    there is no parameter to tamper with. It exposes no community alert, no
    other patient, no surveillance data and no internal agent reasoning.
    """

    permission_classes = (IsPatient,)

    def get(self, request):
        patient = getattr(request.user, "patient_profile", None)
        if patient is None:
            return Response(
                {
                    "detail": (
                        "No patient record is linked to this account. Ask your "
                        "health worker to link it."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        assessments = (
            patient.assessments.filter(is_draft=False)
            .order_by("-encounter_date", "-created_at")[:20]
        )
        followups = patient.followups.filter(
            status=FollowUp.Status.PENDING
        ).order_by("due_date")

        return Response(
            {
                "patient": {
                    "patient_code": patient.patient_code,
                    "display_name": patient.display_name,
                    "age_years": patient.age_years,
                    "village_name": patient.village.name,
                },
                "records": PatientSelfAssessmentSerializer(
                    assessments, many=True
                ).data,
                "followups": [
                    {
                        "id": f.id,
                        "due_date": f.due_date,
                        "status": f.status,
                        "notes": f.notes,
                    }
                    for f in followups
                ],
                "guidance": [
                    "Attend any follow-up visit your health worker has scheduled.",
                    "Return sooner if symptoms worsen or new symptoms appear.",
                    "Keep taking fluids and rest while you are unwell.",
                    "This system does not replace a doctor. For anything urgent, "
                    "contact your PHC or health worker directly.",
                ],
                "scope_note": (
                    "You are seeing only your own health information. Community "
                    "monitoring is handled separately by district health staff."
                ),
                "disclaimer": MEDICAL_DISCLAIMER,
            }
        )
