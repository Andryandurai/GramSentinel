from rest_framework import serializers

from core.constants import MEDICAL_DISCLAIMER

from .models import FollowUp, PatientAssessment


class AssessmentInputSerializer(serializers.Serializer):
    """What the worker portal submits — for both preview and final submit."""

    patient = serializers.IntegerField()
    symptoms = serializers.ListField(
        child=serializers.CharField(allow_blank=False), allow_empty=True, default=list
    )
    raw_symptom_text = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    duration_days = serializers.IntegerField(min_value=0, max_value=365, default=0)
    temperature_c = serializers.FloatField(
        required=False, allow_null=True, min_value=30.0, max_value=45.0
    )
    pulse_bpm = serializers.IntegerField(
        required=False, allow_null=True, min_value=20, max_value=250
    )
    respiratory_rate = serializers.IntegerField(
        required=False, allow_null=True, min_value=5, max_value=90
    )
    systolic_bp = serializers.IntegerField(
        required=False, allow_null=True, min_value=40, max_value=260
    )
    diastolic_bp = serializers.IntegerField(
        required=False, allow_null=True, min_value=20, max_value=180
    )
    spo2 = serializers.IntegerField(
        required=False, allow_null=True, min_value=40, max_value=100
    )
    history = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    encounter_date = serializers.DateField(required=False, allow_null=True)

    def validate(self, attrs):
        if not attrs.get("symptoms") and not attrs.get("raw_symptom_text", "").strip():
            raise serializers.ValidationError(
                {
                    "symptoms": (
                        "Record at least one symptom, or describe the "
                        "presentation in the notes field."
                    )
                }
            )
        return attrs


class PatientAssessmentSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)
    village_name = serializers.CharField(source="village.name", read_only=True)
    worker_name = serializers.CharField(
        source="worker.display_name", read_only=True, default=""
    )
    disclaimer = serializers.SerializerMethodField()

    class Meta:
        model = PatientAssessment
        fields = (
            "id",
            "patient",
            "patient_code",
            "patient_name",
            "village",
            "village_name",
            "worker_name",
            "symptoms",
            "duration_days",
            "temperature_c",
            "pulse_bpm",
            "respiratory_rate",
            "systolic_bp",
            "diastolic_bp",
            "spo2",
            "notes",
            "primary_category",
            "triage_level",
            "triage_score",
            "reasoning_summary",
            "referral_recommendation",
            "followup_interval_days",
            "red_flags",
            "escalation_forced",
            "safety_status",
            "llm_used",
            "encounter_date",
            "aggregated_at",
            "created_at",
            "disclaimer",
        )
        read_only_fields = fields

    def get_disclaimer(self, _obj) -> str:
        return MEDICAL_DISCLAIMER


class FollowUpSerializer(serializers.ModelSerializer):
    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)

    class Meta:
        model = FollowUp
        fields = (
            "id",
            "patient",
            "patient_code",
            "patient_name",
            "assessment",
            "due_date",
            "status",
            "notes",
            "created_at",
        )
        read_only_fields = ("id", "created_at", "patient_code", "patient_name")
