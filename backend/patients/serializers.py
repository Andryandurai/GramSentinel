from rest_framework import serializers

from assessments.models import PatientAssessment

from .models import Patient


class PatientSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    village_code = serializers.CharField(source="village.code", read_only=True)
    assessment_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Patient
        fields = (
            "id",
            "patient_code",
            "display_name",
            "age_years",
            "age_months",
            "sex",
            "village",
            "village_name",
            "village_code",
            "assessment_count",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class PatientSelfAssessmentSerializer(serializers.ModelSerializer):
    """What a patient may see of their own encounter.

    Deliberately narrower than the worker view: no triage score, no agent
    trace, no internal reasoning, no red-flag rule internals. A plain-language
    outcome and what to do next.
    """

    class Meta:
        model = PatientAssessment
        fields = (
            "id",
            "encounter_date",
            "symptoms",
            "duration_days",
            "triage_level",
            "referral_recommendation",
            "followup_interval_days",
        )
        read_only_fields = fields


class PatientCreateSerializer(serializers.ModelSerializer):
    """Patient registration, usable from inside the assessment workflow.

    `patient_code` is optional: a worker registering someone mid-assessment
    should not have to invent an identifier, so one is generated from the
    village code when it is left blank.
    """

    patient_code = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = Patient
        fields = (
            "patient_code",
            "display_name",
            "age_years",
            "age_months",
            "sex",
            "village",
        )

    def validate_patient_code(self, value):
        value = (value or "").strip()
        if value and Patient.objects.filter(patient_code__iexact=value).exists():
            raise serializers.ValidationError(
                "A patient with this identifier already exists."
            )
        return value

    def validate(self, attrs):
        if attrs.get("age_years") is None and attrs.get("age_months") is None:
            raise serializers.ValidationError(
                {"age_years": "Provide age in years or months."}
            )
        if not (attrs.get("display_name") or "").strip():
            raise serializers.ValidationError(
                {"display_name": "Enter a name or local reference for this patient."}
            )
        return attrs

    def create(self, validated_data):
        if not validated_data.get("patient_code"):
            validated_data["patient_code"] = self._next_code(
                validated_data["village"]
            )
        return super().create(validated_data)

    @staticmethod
    def _next_code(village) -> str:
        """Sequential per-village code, e.g. KVL-P-012."""

        prefix = f"{village.code}-P-"
        existing = Patient.objects.filter(
            patient_code__startswith=prefix
        ).values_list("patient_code", flat=True)

        highest = 0
        for code in existing:
            suffix = code[len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return f"{prefix}{highest + 1:03d}"
