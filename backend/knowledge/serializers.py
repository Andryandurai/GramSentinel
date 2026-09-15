from rest_framework import serializers

from .models import KnowledgeDocument


class RuralCareGuidanceRequestSerializer(serializers.Serializer):
    """Exactly the fields `_support_payload()` already returns on an
    assessment preview/submit response — the frontend passes the already-
    computed result straight back, nothing new is entered by the worker."""

    triage_level = serializers.CharField(max_length=32)
    contributing_factors = serializers.ListField(
        child=serializers.CharField(max_length=300), required=False, default=list
    )
    syndrome_groups = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )
    referral_pathway = serializers.CharField(max_length=64, required=False, default="")


class TerminologySuggestionRequestSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=200, allow_blank=False)


class InvestigationGuidanceRequestSerializer(serializers.Serializer):
    """Only an alert id + mode — every evidence field the underlying query
    needs is derived server-side from that alert (see views.py), never
    accepted from the client, so a request cannot fabricate evidence to
    fish for unrelated guidance (Section 45: "no client-controlled source
    authority")."""

    alert_id = serializers.IntegerField()
    mode = serializers.ChoiceField(
        choices=["investigation", "what_if"], required=False, default="investigation"
    )


class ChwKnowledgeRequestSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=500, allow_blank=False)


class KnowledgeDocumentSerializer(serializers.ModelSerializer):
    authority_label = serializers.CharField(source="get_authority_display", read_only=True)
    topic_label = serializers.CharField(source="get_topic_display", read_only=True)
    document_type_label = serializers.CharField(
        source="get_document_type_display", read_only=True
    )

    class Meta:
        model = KnowledgeDocument
        fields = (
            "id",
            "title",
            "organization",
            "authority",
            "authority_label",
            "topic",
            "topic_label",
            "document_type",
            "document_type_label",
            "subtopic",
            "source_url",
            "version",
            "published_date",
            "effective_date",
            "language",
            "jurisdiction",
            "license_note",
            "active",
        )
        read_only_fields = fields
