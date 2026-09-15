"""Work & Communication serializers.

Follows the existing project convention (see `community/serializers.py`,
`users/serializers.py`): a `*_name`/`*_label` read-only companion field for
every FK/choice field, and a separate write-shaped "create/transition"
serializer per action rather than one serializer trying to do both.
"""

from __future__ import annotations

from rest_framework import serializers

from .attachments import AttachmentError, validate_attachment
from .models import (
    CorrectionEvent,
    CorrectionRequest,
    ReportApproval,
    ReportApprovalEvent,
    SupervisorMessage,
    WorkflowStatus,
)

#: Friendly, frontend-facing record-type keys mapped to the actual Django
#: model label — the client names a record by this key and an id; it never
#: sees or supplies the underlying `app_label.model_name` string, and can
#: never widen this to an arbitrary model (`services.correctable_record_or_
#: none` re-validates the resolved label against `CORRECTABLE_MODELS` too).
RECORD_TYPE_CHOICES = {
    "assessment": "assessments.patientassessment",
    "community_report": "community.communityreport",
}
RECORD_TYPE_LABELS = {
    "assessment": "Patient assessment",
    "community_report": "Community report",
}
_MODEL_LABEL_TO_RECORD_TYPE = {v: k for k, v in RECORD_TYPE_CHOICES.items()}


# ---------------------------------------------------------------------------
# Supervisor Communication
# ---------------------------------------------------------------------------
class SupervisorMessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True)
    is_from_officer = serializers.SerializerMethodField()
    has_attachment = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = SupervisorMessage
        fields = (
            "id",
            "sender_name",
            "is_from_officer",
            "subject",
            "body",
            "has_attachment",
            "attachment_filename",
            "attachment_mime",
            "created_at",
            "read_at",
            "is_read",
        )
        read_only_fields = fields

    def get_is_from_officer(self, obj: SupervisorMessage) -> bool:
        return obj.sender_id == obj.officer_id

    def get_has_attachment(self, obj: SupervisorMessage) -> bool:
        return bool(obj.attachment)

    def get_is_read(self, obj: SupervisorMessage) -> bool:
        return obj.read_at is not None


class SupervisorMessageCreateSerializer(serializers.Serializer):
    """What a worker or officer actually supplies. `recipient`/`officer`/
    `worker` are never fields here — the view derives the thread entirely
    from `request.user` (see `views.py`), so there is nothing a client
    could submit to redirect a message to someone else."""

    subject = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    body = serializers.CharField(max_length=8000, allow_blank=False)
    attachment = serializers.CharField(required=False, allow_blank=True, default="")
    attachment_filename = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=200
    )

    def validate(self, attrs):
        try:
            data_uri, filename, mime = validate_attachment(
                attrs.get("attachment") or None, filename=attrs.get("attachment_filename", "")
            )
        except AttachmentError as exc:
            raise serializers.ValidationError({"attachment": str(exc)}) from exc
        attrs["attachment"] = data_uri
        attrs["attachment_filename"] = filename
        attrs["attachment_mime"] = mime
        return attrs


# ---------------------------------------------------------------------------
# Report Approval Tracker
# ---------------------------------------------------------------------------
class ReportApprovalEventSerializer(serializers.ModelSerializer):
    to_status_label = serializers.CharField(source="get_to_status_display", read_only=True)
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="")

    class Meta:
        model = ReportApprovalEvent
        fields = ("from_status", "to_status", "to_status_label", "comment", "actor_name", "created_at")
        read_only_fields = fields


class ReportApprovalSerializer(serializers.ModelSerializer):
    report_id = serializers.IntegerField(source="report.id", read_only=True)
    week_label = serializers.CharField(source="report.week_label", read_only=True)
    period_start = serializers.DateField(source="report.period_start", read_only=True)
    period_end = serializers.DateField(source="report.period_end", read_only=True)
    worker_name = serializers.CharField(source="worker.display_name", read_only=True, default="")
    village_name = serializers.CharField(source="village.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.display_name", read_only=True, default=""
    )
    events = ReportApprovalEventSerializer(many=True, read_only=True)

    class Meta:
        model = ReportApproval
        fields = (
            "id",
            "report_id",
            "week_label",
            "period_start",
            "period_end",
            "worker_name",
            "village_name",
            "status",
            "status_label",
            "supervisor_comment",
            "reviewed_by_name",
            "created_at",
            "updated_at",
            "events",
        )
        read_only_fields = fields


class ReportApprovalTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=WorkflowStatus.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)


# ---------------------------------------------------------------------------
# Correction Requests
# ---------------------------------------------------------------------------
class CorrectionEventSerializer(serializers.ModelSerializer):
    to_status_label = serializers.CharField(source="get_to_status_display", read_only=True)
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default="")

    class Meta:
        model = CorrectionEvent
        fields = ("from_status", "to_status", "to_status_label", "comment", "actor_name", "created_at")
        read_only_fields = fields


class CorrectionRequestSerializer(serializers.ModelSerializer):
    record_type = serializers.SerializerMethodField()
    record_type_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    reviewed_by_name = serializers.CharField(
        source="reviewed_by.display_name", read_only=True, default=""
    )
    events = CorrectionEventSerializer(many=True, read_only=True)

    class Meta:
        model = CorrectionRequest
        fields = (
            "id",
            "record_type",
            "record_type_label",
            "record_label",
            "original_snapshot",
            "mistake_description",
            "proposed_correction",
            "status",
            "status_label",
            "supervisor_comment",
            "reviewed_by_name",
            "applied_at",
            "created_at",
            "updated_at",
            "events",
        )
        read_only_fields = fields

    def get_record_type(self, obj: CorrectionRequest) -> str:
        label = f"{obj.content_type.app_label}.{obj.content_type.model}"
        return _MODEL_LABEL_TO_RECORD_TYPE.get(label, label)

    def get_record_type_label(self, obj: CorrectionRequest) -> str:
        return RECORD_TYPE_LABELS.get(self.get_record_type(obj), "Record")


class CorrectionRequestCreateSerializer(serializers.Serializer):
    """`record_type` + `record_id` name the record; ownership and village
    scope are re-verified server-side against `request.user` in the view
    (`services.correctable_record_or_none`) — never trusted from here."""

    record_type = serializers.ChoiceField(choices=list(RECORD_TYPE_CHOICES))
    record_id = serializers.IntegerField(min_value=1)
    mistake_description = serializers.CharField(max_length=4000, allow_blank=False)
    proposed_correction = serializers.CharField(max_length=4000, allow_blank=False)


class CorrectionTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=WorkflowStatus.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="", max_length=4000)
