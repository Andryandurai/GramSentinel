from __future__ import annotations

import datetime as dt

from rest_framework import serializers

from .models import (
    PicmeRchStatus,
    PregnancyProfile,
    PregnancyProfileEvent,
    PregnancyStatus,
    PregnancyVisitAssessment,
    PregnancyVisitNumber,
)
from .questionnaire import QuestionType, questions_for_visit
from .services import visit_history_status


class PregnancyEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="")

    class Meta:
        model = PregnancyProfileEvent
        fields = ("id", "event_type", "detail", "actor_name", "created_at")
        read_only_fields = fields


class PregnancyVisitAssessmentSerializer(serializers.ModelSerializer):
    visit_label = serializers.CharField(source="get_visit_number_display", read_only=True)
    worker_name = serializers.CharField(source="worker.display_name", read_only=True, default="")

    class Meta:
        model = PregnancyVisitAssessment
        fields = (
            "id",
            "visit_number",
            "visit_label",
            "visit_date",
            "questionnaire_responses",
            "next_checkup_date",
            "warning_signs",
            "rule_flags",
            "ai_guidance",
            "llm_used",
            "worker_name",
            "created_at",
        )
        read_only_fields = fields


class PregnancyProfileSerializer(serializers.ModelSerializer):
    """Worker-facing — village scoping happens in the view (the patient is
    already resolved against the worker's own village before this is ever
    built), same as `PatientAssessmentSerializer`."""

    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    patient_name = serializers.CharField(source="patient.display_name", read_only=True)
    village_name = serializers.CharField(source="village.name", read_only=True)
    assigned_health_worker_name = serializers.CharField(
        source="assigned_health_worker.display_name", read_only=True, default=""
    )
    visits = PregnancyVisitAssessmentSerializer(many=True, read_only=True)
    visit_status = serializers.SerializerMethodField()

    class Meta:
        model = PregnancyProfile
        fields = (
            "id",
            "patient",
            "patient_code",
            "patient_name",
            "village",
            "village_name",
            "picme_rch_id",
            "picme_rch_status",
            "lmp",
            "expected_delivery_date",
            "registration_date",
            "next_checkup_date",
            "assigned_health_worker",
            "assigned_health_worker_name",
            "status",
            "created_at",
            "updated_at",
            "visits",
            "visit_status",
        )
        read_only_fields = (
            "id",
            "patient",
            "patient_code",
            "patient_name",
            "village",
            "village_name",
            "registration_date",
            "assigned_health_worker_name",
            "created_at",
            "updated_at",
            "visits",
            "visit_status",
        )

    def get_visit_status(self, obj: PregnancyProfile) -> dict:
        return visit_history_status(obj)


class PregnancyProfileUpdateSerializer(serializers.Serializer):
    """PATCH input — the PICME note (task §6): never "generate", only record
    what was already issued."""

    picme_rch_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    picme_rch_status = serializers.ChoiceField(choices=PicmeRchStatus.choices, required=False)
    next_checkup_date = serializers.DateField(required=False, allow_null=True)
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    assigned_health_worker = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.ChoiceField(choices=PregnancyStatus.choices, required=False)

    def validate_picme_rch_id(self, value: str) -> str:
        # A reasonable data-storage sanity check, not an invented official
        # format (task §6: "do not invent an official format").
        cleaned = value.strip()
        if cleaned and len(cleaned) < 4:
            raise serializers.ValidationError("Enter the full PICME/RCH ID.")
        return cleaned


class QuestionOptionSerializer(serializers.Serializer):
    key = serializers.CharField()
    text = serializers.CharField()
    type = serializers.CharField()
    warning_sign = serializers.BooleanField()


class VisitInputSerializer(serializers.Serializer):
    """What the Health Worker portal submits to record one pregnancy visit.
    `visit_number` is a controlled enum (task §1: "do not allow arbitrary
    text such as 'third visit maybe'") and `responses` is validated
    key-by-key against that visit's own fixed question set — an unknown key
    or an out-of-vocabulary answer is rejected, never silently dropped or
    coerced (task §4: "missing information must remain NULL; do not store 0
    when the value is unknown")."""

    visit_number = serializers.ChoiceField(choices=PregnancyVisitNumber.values)
    visit_date = serializers.DateField(required=False, allow_null=True)
    responses = serializers.DictField(child=serializers.CharField(allow_blank=True), default=dict)
    next_checkup_date = serializers.DateField(required=False, allow_null=True)
    picme_rch_id = serializers.CharField(required=False, allow_blank=True, max_length=64)
    picme_rch_status = serializers.ChoiceField(choices=PicmeRchStatus.choices, required=False)
    # UI language for the AI guidance narrative only (task §19/§34) — a
    # closed choice, never an arbitrary client string, so the client can
    # never inject an AI system instruction through this field. Every
    # structured field the guidance returns (follow_up_status,
    # warning_signs, rule flags) is identical regardless of this value;
    # only the free-text narrative changes.
    language = serializers.ChoiceField(choices=("en", "ta", "hi"), required=False, default="en")

    def validate(self, attrs):
        visit_number = int(attrs["visit_number"])
        raw_responses = attrs.get("responses") or {}
        questions = questions_for_visit(visit_number)
        valid_keys = {q["key"] for q in questions}

        unknown = set(raw_responses.keys()) - valid_keys
        if unknown:
            raise serializers.ValidationError(
                {"responses": f"Unknown question key(s) for this visit: {sorted(unknown)}"}
            )

        cleaned: dict[str, str] = {}
        lmp_from_visit: dt.date | None = None
        for question in questions:
            key = question["key"]
            if key not in raw_responses:
                continue
            value = (raw_responses[key] or "").strip()
            if not value:
                continue
            if question["type"] == QuestionType.DATE:
                try:
                    lmp_from_visit = dt.date.fromisoformat(value)
                except ValueError:
                    raise serializers.ValidationError({key: "Enter a valid date (YYYY-MM-DD)."})
                continue
            if value not in {"YES", "NO", "UNKNOWN"}:
                raise serializers.ValidationError(
                    {key: "Answer must be YES, NO, or UNKNOWN."}
                )
            cleaned[key] = value

        attrs["responses"] = cleaned
        attrs["lmp_from_visit"] = lmp_from_visit
        return attrs


class OfficerPregnancyListItemSerializer(serializers.ModelSerializer):
    """Officer-facing row (task §16). Uses `patient_code` only, never
    `display_name` — the existing Health Officer permission model does not
    expose individual patient names anywhere else in this codebase, so this
    view does not introduce a new exposure."""

    patient_code = serializers.CharField(source="patient.patient_code", read_only=True)
    village_name = serializers.CharField(source="village.name", read_only=True)
    assigned_health_worker_name = serializers.CharField(
        source="assigned_health_worker.display_name", read_only=True, default=""
    )
    visit_status = serializers.SerializerMethodField()
    last_visit_date = serializers.SerializerMethodField()

    class Meta:
        model = PregnancyProfile
        fields = (
            "id",
            "patient_code",
            "village_name",
            "picme_rch_status",
            "visit_status",
            "last_visit_date",
            "next_checkup_date",
            "status",
            "assigned_health_worker_name",
        )
        read_only_fields = fields

    def get_visit_status(self, obj: PregnancyProfile) -> dict:
        return visit_history_status(obj)

    def get_last_visit_date(self, obj: PregnancyProfile):
        last = obj.visits.order_by("-visit_date", "-id").first()
        return last.visit_date if last else None


class RequestFollowUpInputSerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=("NORMAL", "HIGH", "URGENT"), default="NORMAL")
    due_date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")
