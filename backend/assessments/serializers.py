from django.utils import timezone
from rest_framework import serializers

from core.constants import MEDICAL_DISCLAIMER

from . import followups
from .models import FollowUp, PatientAssessment


#: How many day-wise entries one assessment may carry. The portal offers three;
#: the cap only exists so a malformed payload cannot grow without bound.
MAX_TIMELINE_ENTRIES = 14


class SymptomDayEntrySerializer(serializers.Serializer):
    """One optional day of the symptom history: 'Day 2 — fever increased'."""

    day = serializers.IntegerField(min_value=1, max_value=365)
    detail = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )


class AssessmentInputSerializer(serializers.Serializer):
    """What the worker portal submits — for both preview and final submit."""

    patient = serializers.IntegerField()
    symptoms = serializers.ListField(
        child=serializers.CharField(allow_blank=False), allow_empty=True, default=list
    )
    raw_symptom_text = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    # --- optional "Other" symptom ---------------------------------------
    other_symptom_selected = serializers.BooleanField(required=False, default=False)
    other_symptom_text = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=1000
    )
    duration_days = serializers.IntegerField(min_value=0, max_value=365, default=0)
    # --- optional day-wise symptom history ------------------------------
    symptom_timeline = SymptomDayEntrySerializer(
        many=True, required=False, default=list
    )
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

    def validate_symptom_timeline(self, value):
        """Keep only the days the worker actually filled in.

        Every day is optional: a worker who remembers Day 1 and Day 3 but not
        Day 2 submits exactly that. Blank days are dropped rather than stored
        as empty strings, so nothing shows an empty 'Day 2 —' later on.
        """

        cleaned: dict[int, str] = {}
        for entry in value or []:
            detail = (entry.get("detail") or "").strip()
            if not detail:
                continue
            cleaned[int(entry["day"])] = detail
        return [
            {"day": day, "detail": cleaned[day]}
            for day in sorted(cleaned)[:MAX_TIMELINE_ENTRIES]
        ]

    def validate(self, attrs):
        other_text = (attrs.get("other_symptom_text") or "").strip()
        attrs["other_symptom_text"] = other_text

        # 'Other' is optional, but selecting it and leaving the box empty
        # records nothing at all — so that is refused rather than saved blank.
        if attrs.get("other_symptom_selected") and not other_text:
            raise serializers.ValidationError(
                {
                    "other_symptom_text": (
                        "Describe the symptom, or clear the 'Other' option."
                    )
                }
            )

        if (
            not attrs.get("symptoms")
            and not attrs.get("raw_symptom_text", "").strip()
            and not other_text
        ):
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
            "other_symptom_text",
            "duration_days",
            "symptom_timeline",
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
    """One follow-up, plus the urgency the dashboard sorts and labels by.

    The four derived fields are read-only and computed from what is already
    stored (`due_date`, `status`), so creating a follow-up is unchanged.
    """

    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)
    followup_status = serializers.SerializerMethodField()
    followup_status_label = serializers.SerializerMethodField()
    days_until_due = serializers.SerializerMethodField()
    due_description = serializers.SerializerMethodField()

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
            "followup_status",
            "followup_status_label",
            "days_until_due",
            "due_description",
            "notes",
            "created_at",
        )
        read_only_fields = (
            "id",
            "created_at",
            "patient_code",
            "patient_name",
            "followup_status",
            "followup_status_label",
            "days_until_due",
            "due_description",
        )

    def _today(self):
        # Passed in by the dashboard so every row on one page is judged against
        # the same day; falls back to the server's local date elsewhere.
        return self.context.get("today") or timezone.localdate()

    def get_followup_status(self, obj) -> str:
        return followups.resolve_status(obj.due_date, obj.status, self._today())

    def get_followup_status_label(self, obj) -> str:
        return followups.STATUS_LABELS.get(self.get_followup_status(obj), "")

    def get_days_until_due(self, obj) -> int | None:
        return followups.days_until(obj.due_date, self._today())

    def get_due_description(self, obj) -> str:
        status = self.get_followup_status(obj)
        if status in {followups.COMPLETED, followups.MISSED}:
            return followups.STATUS_LABELS[status]
        return followups.due_description(obj.due_date, self._today())
