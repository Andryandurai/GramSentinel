"""Community reporting and the worker's local-signals view.

Submitting a CHW report does three things in one request: it stores the report,
it pushes the counts through the Integration Layer as normalised signals, and
it re-runs the community pipeline for that village-week. That is the visible
link between "a worker filled in a form" and "an officer has an alert".
"""

from __future__ import annotations

import logging

from django.db import transaction
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from alerts.services import run_community_pipeline
from core.constants import (
    DATA_NOTICE,
    LEGACY_REPORT_FIELDS,
    REPORTABLE_CATEGORIES,
    SYSTEM_CATEGORIES,
    SignalCategory,
    SourceKind,
)
from core.models import Village
from integrations.ingestion import ingest_batch
from users.permissions import IsWorker, IsWorkerOrOfficer

from .models import (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
    DataSource,
)
from .serializers import (
    CommunityReportCreateSerializer,
    CommunityReportSerializer,
    CommunitySignalSerializer,
    DataSourceSerializer,
)

logger = logging.getLogger("gramsentinel.community")

#: Preserved name — the original four categories that have dedicated columns.
REPORT_FIELD_TO_CATEGORY = LEGACY_REPORT_FIELDS


def chw_source_for(village: Village) -> DataSource:
    source, _ = DataSource.objects.get_or_create(
        code=f"CHW-{village.code}",
        defaults={
            "name": f"CHW reports — {village.name}",
            "kind": SourceKind.CHW,
            "channel": DataSource.Channel.PORTAL,
            "village": village,
            "simulated": True,
        },
    )
    return source


def rolling_baseline(source: DataSource, category: str, before_label: str) -> float:
    """This source's own recent normal, not a global norm."""

    previous = (
        CommunitySignal.objects.filter(
            source=source, category=category, is_reported=True
        )
        .exclude(week_label=before_label)
        .order_by("-period_start")
        .values_list("value", flat=True)[:4]
    )
    values = [v for v in previous if v is not None]
    if not values:
        return 1.0
    return max(round(sum(values) / len(values), 2), 1.0)


class CommunityReportListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsWorker,)

    def get_serializer_class(self):
        return (
            CommunityReportCreateSerializer
            if self.request.method == "POST"
            else CommunityReportSerializer
        )

    def get_queryset(self):
        queryset = CommunityReport.objects.select_related("village", "worker")
        if self.request.user.village_id:
            queryset = queryset.filter(village_id=self.request.user.village_id)
        return queryset.order_by("-period_start")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        village = serializer.validated_data["village"]
        if request.user.village_id and village.id != request.user.village_id:
            return Response(
                {"detail": "You may only report for your own village."},
                status=status.HTTP_403_FORBIDDEN,
            )

        entry_inputs = serializer.validated_data.pop("entries", [])

        # Roll the entries up per category so the legacy columns and the
        # ingested signal both reflect the whole report. 'Other' can appear
        # more than once (two unrelated concerns in one week), so counts and
        # descriptions are combined rather than overwritten.
        totals: dict[str, int] = {}
        for entry in entry_inputs:
            totals[entry["category"]] = (
                totals.get(entry["category"], 0) + entry["case_count"]
            )

        legacy_values = {
            field: totals.get(category, serializer.validated_data.get(field, 0) or 0)
            for field, category in REPORT_FIELD_TO_CATEGORY.items()
        }

        report, _created = CommunityReport.objects.update_or_create(
            village=village,
            week_label=serializer.validated_data["week_label"],
            worker=request.user,
            defaults={
                **{
                    k: v
                    for k, v in serializer.validated_data.items()
                    if k not in {"village", "week_label"} | set(LEGACY_REPORT_FIELDS)
                },
                **legacy_values,
                "acknowledged_at": None,  # resubmission is new for the officer
            },
        )

        # Replace this report's entries rather than accumulating duplicates
        # when a worker corrects and resubmits the same week.
        report.entries.all().delete()
        CommunityReportEntry.objects.bulk_create(
            [
                CommunityReportEntry(
                    report=report,
                    category=entry["category"],
                    case_count=entry["case_count"],
                    description=(entry.get("description") or "").strip(),
                    notes=(entry.get("notes") or "").strip(),
                )
                for entry in entry_inputs
            ]
        )

        # Stage 1 — through the Integration Layer like any other source. Every
        # reported category is ingested, not only the original four.
        source = chw_source_for(village)
        reported_categories = {
            **{c: 0 for c in REPORT_FIELD_TO_CATEGORY.values()},
            **totals,
        }
        records = [
            {
                "source_code": source.code,
                "category": category,
                "week_label": report.week_label,
                "value": count,
                "baseline": rolling_baseline(source, category, report.week_label),
                "is_reported": True,
                "data_quality": "GOOD",
                "metadata": {"unusual_observation": report.unusual_observation},
            }
            for category, count in reported_categories.items()
            if category not in SYSTEM_CATEGORIES
        ]
        event = ingest_batch(
            records,
            channel=DataSource.Channel.PORTAL,
            week_label=report.week_label,
        )

        # Stages 2-5 for the categories this report actually moved.
        pipeline_outcomes = []
        for category, count in sorted(reported_categories.items()):
            if count <= 0 or category in SYSTEM_CATEGORIES:
                continue
            outcome = run_community_pipeline(village, report.week_label, category)
            pipeline_outcomes.append(
                {
                    "category": category,
                    "label": SignalCategory(category).label,
                    "reported_cases": count,
                    "alert_raised": outcome["alert_raised"],
                    "reason": outcome["reason"],
                    "safety_verdict": outcome["safety"]["verdict"],
                    "safety_status": outcome["safety"]["status"],
                    "corroborating_source_count": outcome["safety"][
                        "corroborating_source_count"
                    ],
                    "alert_uid": (
                        str(outcome["alert"].alert_uid) if outcome["alert"] else None
                    ),
                }
            )

        described = [
            e for e in report.entries.all() if e.description.strip()
        ]

        return Response(
            {
                "report": CommunityReportSerializer(report).data,
                "ingestion": {
                    "channel": event.channel,
                    "records_received": event.records_received,
                    "records_accepted": event.records_accepted,
                    "records_rejected": event.records_rejected,
                    "records_deduplicated": event.records_deduplicated,
                    "result": event.result,
                },
                "pipeline": pipeline_outcomes,
                "described_observations": len(described),
                "officer_note": (
                    f"This report is now visible to the health officer for "
                    f"{village.name}."
                ),
                "data_notice": DATA_NOTICE,
            },
            status=status.HTTP_201_CREATED,
        )


class ReportCategoryListView(APIView):
    """The category vocabulary the report form renders.

    Served from the backend so the form and the stored values can never drift
    apart.
    """

    permission_classes = (IsWorkerOrOfficer,)

    def get(self, _request):
        from core.constants import DESCRIPTION_REQUIRED_CATEGORIES

        return Response(
            {
                "categories": [
                    {
                        "value": value,
                        "label": SignalCategory(value).label,
                        "description_required": value
                        in DESCRIPTION_REQUIRED_CATEGORIES,
                    }
                    for value in REPORTABLE_CATEGORIES
                ],
                "note": (
                    "These are community health signal categories. Counts are "
                    "reported or observed cases, not confirmed diagnoses."
                ),
            }
        )


class LocalSignalsView(APIView):
    """A worker's own-area view.

    Scoped deliberately: a worker sees signals for their village so they are
    informed rather than bypassed, but never district-wide surveillance detail
    and never another area's alerts.
    """

    permission_classes = (IsWorker,)

    def get(self, request):
        village = request.user.village
        if village is None:
            return Response(
                {
                    "village": None,
                    "signals": [],
                    "message": "No village is assigned to this account.",
                }
            )

        signals = list(
            CommunitySignal.objects.filter(village=village)
            .select_related("source")
            .order_by("-period_start", "category", "source__kind")[:200]
        )

        category_filter = self.request.query_params.get("category")
        if category_filter:
            signals = [s for s in signals if s.category == category_filter]

        rising = [
            s for s in signals if s.change_pct is not None and s.change_pct >= 30.0
        ]
        if rising:
            labels = sorted({s.get_category_display() for s in rising})
            headline = (
                f"{', '.join(labels)} — reported signals are above the recent "
                f"baseline in {village.name}. Community-level review is handled "
                "by the health officer for your area."
            )
        else:
            headline = (
                f"No reported signal in {village.name} is notably above its "
                "recent baseline."
            )

        # Group by category so an expanded vocabulary stays readable rather
        # than becoming one long undifferentiated list.
        grouped: dict[str, dict] = {}
        for signal in signals:
            bucket = grouped.setdefault(
                signal.category,
                {
                    "category": signal.category,
                    "label": signal.get_category_display(),
                    "is_rising": False,
                    "signals": [],
                },
            )
            bucket["signals"].append(CommunitySignalSerializer(signal).data)
            if signal.change_pct is not None and signal.change_pct >= 30.0:
                bucket["is_rising"] = True

        return Response(
            {
                "village": {
                    "code": village.code,
                    "name": village.name,
                    "cluster": village.cluster,
                },
                "headline": headline,
                "rising_categories": sorted(
                    {s.get_category_display() for s in rising}
                ),
                # Flat list preserved for anything already consuming it.
                "signals": CommunitySignalSerializer(signals, many=True).data,
                "grouped": sorted(
                    grouped.values(),
                    key=lambda g: (not g["is_rising"], g["label"]),
                ),
                "scope_note": (
                    "Local signals for your own area only. District-wide "
                    "surveillance detail is not shown here."
                ),
                "signal_note": (
                    "These are reported community health signals, not confirmed "
                    "diagnoses."
                ),
                "data_notice": DATA_NOTICE,
            }
        )


class DataSourceListView(generics.ListAPIView):
    """Which sources are registered and how each would arrive in a real deployment."""

    permission_classes = (IsWorkerOrOfficer,)
    serializer_class = DataSourceSerializer

    def get_queryset(self):
        queryset = DataSource.objects.select_related("village")
        village_code = self.request.query_params.get("village")
        if village_code:
            queryset = queryset.filter(village__code=village_code)
        return queryset.order_by("village__name", "kind")
