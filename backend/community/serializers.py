from rest_framework import serializers

from core.constants import (
    DESCRIPTION_REQUIRED_CATEGORIES,
    LEGACY_REPORT_FIELDS,
    REPORTABLE_CATEGORIES,
    SignalCategory,
)

from .models import (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
    DataSource,
)


class CommunityReportSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)
    worker_name = serializers.CharField(
        source="worker.display_name", read_only=True, default=""
    )
    entries = serializers.SerializerMethodField()
    total_reported_cases = serializers.IntegerField(read_only=True)

    class Meta:
        model = CommunityReport
        fields = (
            "id",
            "village",
            "village_name",
            "worker_name",
            "week_label",
            "period_start",
            "period_end",
            "fever_cases",
            "respiratory_cases",
            "diarrhoeal_cases",
            "other_cases",
            "unusual_observation",
            "notes",
            "entries",
            "total_reported_cases",
            "submitted_at",
        )
        read_only_fields = ("id", "submitted_at", "village_name", "worker_name")

    def get_entries(self, obj):
        return CommunityReportEntrySerializer(obj.entries.all(), many=True).data


class CommunityReportEntrySerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = CommunityReportEntry
        fields = ("id", "category", "label", "case_count", "description", "notes")
        read_only_fields = ("id", "label")


class CommunityReportEntryInputSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=REPORTABLE_CATEGORIES)
    case_count = serializers.IntegerField(min_value=0, max_value=100000, default=0)
    description = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000
    )
    notes = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=2000
    )

    def validate(self, attrs):
        category = attrs["category"]
        description = (attrs.get("description") or "").strip()

        # A category like "Other" tells an officer nothing on its own — the
        # worker's own words are the entire content of the report.
        if category in DESCRIPTION_REQUIRED_CATEGORIES and not description:
            raise serializers.ValidationError(
                {
                    "description": (
                        f"Describe what was observed for "
                        f"'{SignalCategory(category).label}'."
                    )
                }
            )
        if attrs.get("case_count", 0) == 0 and not description:
            raise serializers.ValidationError(
                {
                    "case_count": (
                        "Enter a number of reported cases, or describe what was "
                        "observed."
                    )
                }
            )
        return attrs


class CommunityReportCreateSerializer(serializers.ModelSerializer):
    """Accepts the expanded category set as a list of entries.

    The four legacy `*_cases` columns remain on the model and are kept in sync
    from the entries, so nothing that reads them breaks.
    """

    entries = CommunityReportEntryInputSerializer(many=True, required=False)

    class Meta:
        model = CommunityReport
        fields = (
            "village",
            "week_label",
            "period_start",
            "period_end",
            "fever_cases",
            "respiratory_cases",
            "diarrhoeal_cases",
            "other_cases",
            "unusual_observation",
            "notes",
            "entries",
        )

    def validate(self, attrs):
        if attrs["period_end"] < attrs["period_start"]:
            raise serializers.ValidationError(
                {"period_end": "Reporting period ends before it starts."}
            )

        entries = attrs.get("entries") or []
        legacy_total = sum(
            attrs.get(field, 0) or 0 for field in LEGACY_REPORT_FIELDS
        )
        if not entries and legacy_total == 0:
            raise serializers.ValidationError(
                {
                    "entries": (
                        "Add at least one reported category, or record a "
                        "described observation."
                    )
                }
            )

        seen: set[str] = set()
        for entry in entries:
            category = entry["category"]
            # 'Other' may legitimately appear more than once — two unrelated
            # concerns in one week — but a named category should not.
            if category != SignalCategory.OTHER:
                if category in seen:
                    raise serializers.ValidationError(
                        {
                            "entries": (
                                f"'{SignalCategory(category).label}' is listed "
                                "more than once."
                            )
                        }
                    )
                seen.add(category)
        return attrs


class CommunitySignalSerializer(serializers.ModelSerializer):
    source_kind = serializers.CharField(source="source.kind", read_only=True)
    source_name = serializers.CharField(source="source.name", read_only=True)
    change_pct = serializers.FloatField(read_only=True)

    class Meta:
        model = CommunitySignal
        fields = (
            "id",
            "source_kind",
            "source_name",
            "category",
            "week_label",
            "period_start",
            "period_end",
            "value",
            "baseline",
            "unit",
            "change_pct",
            "is_reported",
            "data_quality",
        )
        read_only_fields = fields


class DataSourceSerializer(serializers.ModelSerializer):
    village_name = serializers.CharField(source="village.name", read_only=True)

    class Meta:
        model = DataSource
        fields = (
            "id",
            "code",
            "name",
            "kind",
            "channel",
            "village",
            "village_name",
            "is_active",
            "simulated",
        )
        read_only_fields = fields
