from rest_framework import serializers

from core.constants import DATA_NOTICE

from .models import Alert, AlertEvidence, Feedback, Investigation, SafetyCheck


class AlertEvidenceSerializer(serializers.ModelSerializer):
    source_kind_display = serializers.CharField(
        source="get_source_kind_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    class Meta:
        model = AlertEvidence
        fields = (
            "id",
            "source_kind",
            "source_kind_display",
            "source_name",
            "category",
            "village_code",
            "week_label",
            "baseline",
            "current_value",
            "change_pct",
            "unit",
            "data_quality",
            "status",
            "status_display",
            "is_corroborating",
            "explanation",
            "produced_by_agent",
        )
        read_only_fields = fields


class SafetyCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafetyCheck
        fields = (
            "id",
            "scope",
            "verdict",
            "passed",
            "status",
            "rules",
            "reasons",
            "engine_version",
            "week_label",
            "created_at",
        )
        read_only_fields = fields


class InvestigationSerializer(serializers.ModelSerializer):
    officer_name = serializers.CharField(
        source="officer.display_name", read_only=True, default=""
    )

    class Meta:
        model = Investigation
        fields = (
            "id",
            "status",
            "notes",
            "officer_name",
            "started_at",
            "updated_at",
        )
        read_only_fields = fields


class FeedbackSerializer(serializers.ModelSerializer):
    officer_name = serializers.CharField(
        source="officer.display_name", read_only=True, default=""
    )

    class Meta:
        model = Feedback
        fields = (
            "id",
            "outcome",
            "notes",
            "officer_name",
            "resolution_latency_seconds",
            "created_at",
        )
        read_only_fields = fields


class AlertListSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    village_code = serializers.CharField(source="village.code", read_only=True)
    outcome = serializers.CharField(
        source="feedback.outcome", read_only=True, default=None
    )

    class Meta:
        model = Alert
        fields = (
            "id",
            "alert_uid",
            "title",
            "cluster",
            "village_name",
            "village_code",
            "category",
            "week_label",
            "period_start",
            "period_end",
            "severity",
            "confidence",
            "corroborating_source_count",
            "cross_level_verdict",
            "safety_verdict",
            "safety_status",
            "status",
            "outcome",
            "created_at",
        )
        read_only_fields = fields


class AlertDetailSerializer(AlertListSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    evidence = AlertEvidenceSerializer(many=True, read_only=True)
    safety_check = serializers.SerializerMethodField()
    investigation = InvestigationSerializer(read_only=True)
    feedback = FeedbackSerializer(read_only=True)
    requires_human_review = serializers.BooleanField(read_only=True)
    data_notice = serializers.SerializerMethodField()

    class Meta(AlertListSerializer.Meta):
        fields = AlertListSerializer.Meta.fields + (
            "summary",
            "cross_level_statement",
            "narrative_used_llm",
            "orchestration_run_id",
            "evidence",
            "safety_check",
            "investigation",
            "feedback",
            "requires_human_review",
            "data_notice",
        )
        read_only_fields = fields

    def get_safety_check(self, obj):
        check = obj.safety_checks.order_by("-created_at").first()
        return SafetyCheckSerializer(check).data if check else None

    def get_data_notice(self, _obj) -> str:
        return DATA_NOTICE


class AlertStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Alert.Status.choices)
    investigation_status = serializers.ChoiceField(
        choices=Investigation.Status.choices, required=False
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class FeedbackInputSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=Feedback.Outcome.choices)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
