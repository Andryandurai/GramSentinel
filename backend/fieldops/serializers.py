"""Field Operations serializers — same convention as the rest of this
project (see `community/serializers.py`, `workspace/serializers.py`): a
`*_name`/`*_label` read-only companion for every FK/choice field, and a
separate create/transition serializer per action.
"""

from __future__ import annotations

from rest_framework import serializers

from .attachments import AttachmentError, validate_inspection_attachment
from .models import (
    ActionPlan,
    ActionPlanProgressUpdate,
    ChecklistItemTemplate,
    Department,
    FieldVisit,
    Inspection,
    InspectionAttachment,
    InspectionChecklistResponse,
    Priority,
)


# ---------------------------------------------------------------------------
# Field Visits
# ---------------------------------------------------------------------------
class FieldVisitSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    village_code = serializers.CharField(source="village.code", read_only=True)
    assigned_officer_name = serializers.CharField(source="assigned_officer.display_name", read_only=True)
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True, default="")
    is_overdue = serializers.BooleanField(read_only=True)

    class Meta:
        model = FieldVisit
        fields = (
            "id", "village", "village_name", "village_code",
            "assigned_officer", "assigned_officer_name",
            "visit_date", "start_time", "end_time",
            "objective", "priority", "priority_label", "status", "status_label", "notes",
            "outcome_summary", "observations", "issues_identified", "follow_up_required",
            "completed_at", "is_overdue",
            "created_by_name", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "village_name", "village_code", "assigned_officer_name",
            "priority_label", "status", "status_label",
            "outcome_summary", "observations", "issues_identified", "follow_up_required",
            "completed_at", "is_overdue", "created_by_name", "created_at", "updated_at",
        )


class FieldVisitCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FieldVisit
        fields = ("village", "assigned_officer", "visit_date", "start_time", "end_time", "objective", "priority", "notes")

    def validate(self, attrs):
        start = attrs.get("start_time")
        end = attrs.get("end_time")
        if start and end and end <= start:
            raise serializers.ValidationError({"end_time": "End time must be after the start time."})
        officer = attrs.get("assigned_officer")
        village = attrs.get("village")
        if officer and village and officer.village_id != village.id:
            raise serializers.ValidationError(
                {"assigned_officer": "The assigned officer must belong to the selected village."}
            )
        if officer and officer.role != "HEALTH_OFFICER":
            raise serializers.ValidationError({"assigned_officer": "Only a Health Officer can be assigned a field visit."})
        return attrs


class FieldVisitOutcomeSerializer(serializers.Serializer):
    outcome_summary = serializers.CharField(max_length=4000, allow_blank=True, default="")
    observations = serializers.CharField(max_length=4000, allow_blank=True, default="")
    issues_identified = serializers.CharField(max_length=4000, allow_blank=True, default="")
    follow_up_required = serializers.BooleanField(default=False)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
class ChecklistItemTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChecklistItemTemplate
        fields = ("id", "category", "text", "order")
        read_only_fields = fields


class InspectionChecklistResponseSerializer(serializers.ModelSerializer):
    item_text = serializers.CharField(source="template_item.text", read_only=True)
    status_label = serializers.SerializerMethodField()

    class Meta:
        model = InspectionChecklistResponse
        fields = ("id", "template_item", "item_text", "status", "status_label", "remarks", "updated_at")
        read_only_fields = ("id", "template_item", "item_text", "status_label", "updated_at")

    def get_status_label(self, obj: InspectionChecklistResponse) -> str:
        return obj.get_status_display() if obj.status else "Not reviewed"


class InspectionChecklistResponseUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["PASSED", "FAILED", "NEEDS_ACTION"])
    remarks = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate(self, attrs):
        # Task: "Keep remarks optional unless the item is Failed or Needs
        # Action" — enforced here, consistently, for both values.
        if attrs["status"] in {"FAILED", "NEEDS_ACTION"} and not attrs.get("remarks", "").strip():
            raise serializers.ValidationError(
                {"remarks": "Add a remark explaining what needs attention."}
            )
        return attrs


class InspectionAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source="uploaded_by.display_name", read_only=True, default="")

    class Meta:
        model = InspectionAttachment
        fields = ("id", "filename", "mime", "uploaded_by_name", "created_at")
        read_only_fields = fields


class InspectionAttachmentCreateSerializer(serializers.Serializer):
    file = serializers.CharField()
    filename = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)

    def validate(self, attrs):
        try:
            data_uri, filename, mime = validate_inspection_attachment(attrs["file"], filename=attrs.get("filename", ""))
        except AttachmentError as exc:
            raise serializers.ValidationError({"file": str(exc)}) from exc
        attrs["file"] = data_uri
        attrs["filename"] = filename
        attrs["mime"] = mime
        return attrs


class InspectionSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    officer_name = serializers.CharField(source="officer.display_name", read_only=True)
    inspection_type_label = serializers.CharField(source="get_inspection_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    responses = InspectionChecklistResponseSerializer(many=True, read_only=True)
    attachments = InspectionAttachmentSerializer(many=True, read_only=True)
    summary = serializers.SerializerMethodField()

    class Meta:
        model = Inspection
        fields = (
            "id", "village", "village_name", "officer", "officer_name",
            "inspection_type", "inspection_type_label", "inspection_date",
            "status", "status_label", "summary_remarks", "completed_at",
            "responses", "attachments", "summary", "created_at", "updated_at",
        )
        read_only_fields = fields

    def get_summary(self, obj: Inspection) -> dict[str, int]:
        from .services import checklist_summary

        return checklist_summary(obj)


class InspectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inspection
        fields = ("village", "inspection_type", "inspection_date")

    def validate_inspection_date(self, value):
        return value


class InspectionSummaryRemarksSerializer(serializers.Serializer):
    summary_remarks = serializers.CharField(max_length=4000, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Action Plans
# ---------------------------------------------------------------------------
class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name")
        read_only_fields = fields


class ActionPlanProgressUpdateSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source="updated_by.display_name", read_only=True, default="")

    class Meta:
        model = ActionPlanProgressUpdate
        fields = ("previous_percentage", "new_percentage", "update_note", "updated_by_name", "created_at")
        read_only_fields = fields


class ActionPlanSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    source_type_label = serializers.CharField(source="get_source_type_display", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    responsible_officer_name = serializers.CharField(
        source="responsible_officer.display_name", read_only=True, default=""
    )
    priority_label = serializers.CharField(source="get_priority_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True, default="")
    progress_updates = ActionPlanProgressUpdateSerializer(many=True, read_only=True)

    class Meta:
        model = ActionPlan
        fields = (
            "id", "village", "village_name", "title", "problem_finding",
            "source_type", "source_type_label", "source_field_visit", "source_inspection", "source_checklist_item",
            "department", "department_name", "responsible_officer", "responsible_officer_name",
            "deadline", "required_resources", "priority", "priority_label",
            "progress_percentage", "status", "status_label", "is_overdue", "notes",
            "created_by_name", "created_at", "updated_at", "completed_at", "progress_updates",
        )
        read_only_fields = (
            "id", "village_name", "source_type_label", "department_name", "responsible_officer_name",
            "priority_label", "status", "status_label", "is_overdue",
            "created_by_name", "created_at", "updated_at", "completed_at", "progress_updates",
        )


class ActionPlanCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActionPlan
        fields = (
            "title", "problem_finding", "village",
            "source_type", "source_field_visit", "source_inspection", "source_checklist_item",
            "department", "responsible_officer",
            "deadline", "required_resources", "priority", "progress_percentage", "notes",
        )
        extra_kwargs = {"progress_percentage": {"default": 0}}

    def validate(self, attrs):
        village = attrs.get("village")
        source_type = attrs.get("source_type", "OTHER")
        visit = attrs.get("source_field_visit")
        inspection = attrs.get("source_inspection")
        checklist_item = attrs.get("source_checklist_item")

        if source_type == "FIELD_VISIT" and visit is None:
            raise serializers.ValidationError({"source_field_visit": "Select the field visit this action plan is for."})
        if source_type == "INSPECTION" and inspection is None:
            raise serializers.ValidationError({"source_inspection": "Select the inspection this action plan is for."})

        # Cross-village linking is refused outright — never merely warned
        # about (task: "Prevent cross-village object linking").
        if visit is not None and village is not None and visit.village_id != village.id:
            raise serializers.ValidationError({"source_field_visit": "That field visit belongs to a different village."})
        if inspection is not None and village is not None and inspection.village_id != village.id:
            raise serializers.ValidationError({"source_inspection": "That inspection belongs to a different village."})
        if checklist_item is not None and inspection is not None and checklist_item.inspection_id != inspection.id:
            raise serializers.ValidationError(
                {"source_checklist_item": "That checklist item does not belong to the selected inspection."}
            )

        officer = attrs.get("responsible_officer")
        if officer is not None and village is not None and officer.village_id != village.id:
            raise serializers.ValidationError(
                {"responsible_officer": "The responsible person must belong to the selected village."}
            )

        progress = attrs.get("progress_percentage", 0)
        if not 0 <= progress <= 100:
            raise serializers.ValidationError({"progress_percentage": "Progress must be between 0 and 100."})
        return attrs


class ActionPlanProgressInputSerializer(serializers.Serializer):
    new_percentage = serializers.IntegerField(min_value=0, max_value=100)
    update_note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


PRIORITY_CHOICES = Priority.choices
