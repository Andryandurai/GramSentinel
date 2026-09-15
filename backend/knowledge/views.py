"""RAG endpoints — a small, explicitly-scoped set (Section 41 of the
task: "do not blindly create all endpoints... do not create a generic
unrestricted RAG endpoint"). Every endpoint below is gated by the same
role permission classes the operational endpoints next to it already use,
and every one builds its query from server-derived data (an alert looked
up through the existing village-scoped `officer_alert_queryset`, or fields
that are simply the already-computed result the frontend is showing) —
never from a client-supplied village id or a client-supplied evidence
shape.
"""

from __future__ import annotations

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from alerts.views import officer_alert_queryset
from core.constants import SignalCategory
from users.permissions import IsHealthOfficer, IsWorker, IsWorkerOrOfficer

from . import queries
from .models import KnowledgeDocument
from .serializers import (
    ChwKnowledgeRequestSerializer,
    InvestigationGuidanceRequestSerializer,
    KnowledgeDocumentSerializer,
    RuralCareGuidanceRequestSerializer,
    TerminologySuggestionRequestSerializer,
)


class RuralCareGuidanceView(APIView):
    """Modules 1 + 3 + 4 — called after the existing RuralCare pipeline
    has already produced a triage result. Never touches PatientAssessment,
    never receives a patient id — the frontend passes back only the
    TriageSupport fields it is already displaying."""

    permission_classes = (IsWorker,)

    def post(self, request):
        serializer = RuralCareGuidanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        result = queries.ruralcare_guidance(
            triage_level=data["triage_level"],
            contributing_factors=data["contributing_factors"],
            syndrome_groups=data["syndrome_groups"],
            referral_pathway=data["referral_pathway"],
            user=request.user,
        )
        return Response(result)


class TerminologySuggestionView(APIView):
    """Module 2 — only ever meaningful for text the deterministic
    vocabulary already failed to recognise; the frontend is responsible
    for only calling this for `unrecognised_entries` (Section 16)."""

    permission_classes = (IsWorker,)

    def post(self, request):
        serializer = TerminologySuggestionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = queries.terminology_suggestion(
            entered_text=serializer.validated_data["text"], user=request.user
        )
        return Response(result)


class InvestigationGuidanceView(APIView):
    """Modules 5 + 6 + 7 + 9 + 10 — the evidence shape is derived here,
    server-side, from the same village-scoped `officer_alert_queryset()`
    every other alert endpoint uses, exactly like `AlertEvidenceView`
    already does. An officer cannot request guidance for an alert outside
    their own village scope (404, not 403 — same as every other alert
    lookup in this project, so existence is never confirmed to an
    unauthorized officer either)."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request):
        serializer = InvestigationGuidanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        alert = generics.get_object_or_404(
            officer_alert_queryset(request.user), pk=data["alert_id"]
        )
        evidence = list(alert.evidence.all())
        corroborating = [e.source_kind for e in evidence if e.is_corroborating]
        context_only = [e.source_kind for e in evidence if e.status == "SUPPORTING_CONTEXT"]
        missing = [e.source_kind for e in evidence if e.status == "NOT_REPORTED"]
        operationally_unavailable = [
            e.source_kind for e in evidence if e.status == "EXPECTED_UNAVAILABLE"
        ]

        result = queries.investigation_guidance(
            category_label=SignalCategory(alert.category).label,
            corroborating_sources=corroborating,
            context_sources=context_only,
            missing_sources=missing,
            operationally_unavailable_sources=operationally_unavailable,
            cross_level_verdict=alert.cross_level_verdict,
            safety_verdict=alert.safety_verdict,
            mode=data["mode"],
            user=request.user,
        )
        return Response(result)


class ChwKnowledgeView(APIView):
    """Module 8 — the only endpoint taking free text directly from a
    worker, scoped to a single fixed topic the client cannot change."""

    permission_classes = (IsWorker,)

    def post(self, request):
        serializer = ChwKnowledgeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = queries.chw_knowledge(
            worker_question=serializer.validated_data["question"], user=request.user
        )
        return Response(result)


class KnowledgeDocumentDetailView(generics.RetrieveAPIView):
    """Backs a citation's "[View source]" — read-only, active documents
    only (a superseded/deactivated document is never link-followable from
    a currently-shown citation, since it can no longer be retrieved for a
    new citation either)."""

    permission_classes = (IsWorkerOrOfficer,)
    serializer_class = KnowledgeDocumentSerializer
    queryset = KnowledgeDocument.objects.filter(active=True)
