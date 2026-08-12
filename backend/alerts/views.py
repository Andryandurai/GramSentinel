"""Officer-facing endpoints — Stages 5 and 6.

The Evidence View endpoint is the one the demonstration turns on: it answers
"why was this alert generated?" with the contributing sources, the agent
handoffs, the cross-level verdict and the per-rule safety result, rather than a
score.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from community.models import (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
)
from core.constants import DATA_NOTICE, MEDICAL_DISCLAIMER, SYSTEM_CATEGORIES, SignalCategory
from core.trends import (
    DECREASING,
    INCREASING,
    INSUFFICIENT_DATA,
    STABLE,
    compute_trend,
    period_windows,
)
from users.permissions import IsHealthOfficer
from users.scoping import scope_queryset, scoped_village_id

from .models import AgentRun, Alert, Feedback, Investigation
from .serializers import (
    AlertDetailSerializer,
    AlertEvidenceSerializer,
    AlertListSerializer,
    AlertStatusSerializer,
    FeedbackInputSerializer,
    FeedbackSerializer,
    SafetyCheckSerializer,
)


class OfficerDashboardView(APIView):
    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        # An officer assigned to a village sees that village only; one with no
        # village assigned supervises the whole district (see users/scoping.py).
        alerts = scope_queryset(
            Alert.objects.select_related("village").prefetch_related("feedback"),
            request.user,
        )
        active = alerts.exclude(status=Alert.Status.CLOSED)

        outcome_counts = dict(
            Feedback.objects.filter(alert__in=alerts)
            .values_list("outcome")
            .annotate(n=Count("id"))
        )

        # Community reports from this officer's area, newest first.
        reports = scope_queryset(
            CommunityReport.objects.select_related("village", "worker").prefetch_related(
                "entries"
            ),
            request.user,
        ).order_by("-submitted_at")
        unread_reports = reports.filter(acknowledged_at__isnull=True).count()

        # Trend series for the officer's charts: one point per week per source
        # kind, aggregated across the villages this officer can see.
        signals = (
            scope_queryset(
                CommunitySignal.objects.filter(is_reported=True), request.user
            )
            .select_related("source", "village")
            .order_by("period_start")
        )
        series: dict[str, list[dict]] = {}
        for signal in signals:
            series.setdefault(signal.source.kind, []).append(
                {
                    "week_label": signal.week_label,
                    "value": signal.value,
                    "baseline": signal.baseline,
                    "category": signal.category,
                    "village": signal.village.code,
                }
            )

        return Response(
            {
                "officer": request.user.display_name,
                "district": request.user.district,
                "scope": {
                    "village_code": (
                        request.user.village.code if request.user.village else None
                    ),
                    "village_name": (
                        request.user.village.name if request.user.village else None
                    ),
                    "is_district_wide": scoped_village_id(request.user) is None,
                },
                "new_reports": unread_reports,
                "recent_reports": [
                    {
                        "id": report.id,
                        "village_name": report.village.name,
                        "village_code": report.village.code,
                        "worker_name": (
                            report.worker.display_name if report.worker else "—"
                        ),
                        "week_label": report.week_label,
                        "submitted_at": report.submitted_at,
                        "unusual_observation": report.unusual_observation,
                        "acknowledged": report.acknowledged_at is not None,
                        "total_cases": sum(e.case_count for e in report.entries.all()),
                        "categories": [
                            {
                                "category": entry.category,
                                "label": entry.get_category_display(),
                                "case_count": entry.case_count,
                                "description": entry.description,
                            }
                            for entry in report.entries.all()
                            if entry.case_count > 0 or entry.description
                        ],
                    }
                    for report in reports[:8]
                ],
                "summary": {
                    "active_alerts": active.count(),
                    "under_investigation": alerts.filter(
                        status=Alert.Status.UNDER_INVESTIGATION
                    ).count(),
                    "closed_alerts": alerts.filter(status=Alert.Status.CLOSED).count(),
                    "high_severity": active.filter(severity=Alert.Severity.HIGH).count(),
                    "safety_passed": alerts.filter(safety_verdict="PASS").count(),
                    "safety_downgraded": alerts.filter(
                        safety_verdict="DOWNGRADE"
                    ).count(),
                    "villages_monitored": (
                        signals.values("village").distinct().count()
                    ),
                    "mean_confidence": round(
                        alerts.aggregate(v=Avg("confidence"))["v"] or 0.0, 2
                    ),
                    "human_review_rate": 1.0,
                },
                "outcomes": {
                    "valid_signal": outcome_counts.get("VALID_SIGNAL", 0),
                    "false_alert": outcome_counts.get("FALSE_ALERT", 0),
                    "resolved": outcome_counts.get("RESOLVED", 0),
                },
                "alerts": AlertListSerializer(
                    active.order_by("-created_at")[:20], many=True
                ).data,
                "trends": series,
                "disclaimer": MEDICAL_DISCLAIMER,
                "data_notice": DATA_NOTICE,
            }
        )


def officer_alert_queryset(user):
    """Alerts one officer may see. Used by every officer alert endpoint so a
    village-scoped officer cannot reach another village's alert by id."""

    return scope_queryset(
        Alert.objects.select_related("village").prefetch_related(
            "evidence", "safety_checks", "feedback"
        ),
        user,
    )


class AlertListView(generics.ListAPIView):
    permission_classes = (IsHealthOfficer,)
    serializer_class = AlertListSerializer

    def get_queryset(self):
        queryset = officer_alert_queryset(self.request.user)
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if self.request.query_params.get("history") == "1":
            queryset = queryset.filter(
                Q(status=Alert.Status.CLOSED) | Q(feedback__isnull=False)
            )
        return queryset.order_by("-created_at")


class AlertDetailView(generics.RetrieveAPIView):
    permission_classes = (IsHealthOfficer,)
    serializer_class = AlertDetailSerializer
    lookup_field = "pk"

    def get_queryset(self):
        return officer_alert_queryset(self.request.user)


class AlertEvidenceView(APIView):
    """Everything behind the alert, in the order it was produced."""

    permission_classes = (IsHealthOfficer,)

    def get(self, request, pk: int):
        alert = generics.get_object_or_404(
            officer_alert_queryset(request.user), pk=pk
        )
        evidence = alert.evidence.all()
        safety_check = alert.safety_checks.order_by("-created_at").first()

        runs = AgentRun.objects.filter(run_id=alert.orchestration_run_id).order_by(
            "sequence"
        )

        corroborating = [e for e in evidence if e.is_corroborating]
        context_only = [
            e for e in evidence if e.status == "SUPPORTING_CONTEXT"
        ]
        missing = [e for e in evidence if e.status == "NOT_REPORTED"]

        return Response(
            {
                "alert": {
                    "id": alert.id,
                    "alert_uid": str(alert.alert_uid),
                    "title": alert.title,
                    "summary": alert.summary,
                    "cluster": alert.cluster,
                    "village": alert.village.name,
                    "category": alert.category,
                    "week_label": alert.week_label,
                    "period_start": alert.period_start,
                    "period_end": alert.period_end,
                    "severity": alert.severity,
                    "confidence": alert.confidence,
                    "status": alert.status,
                    "narrative_used_llm": alert.narrative_used_llm,
                },
                "why_this_alert": {
                    "corroborating_sources": [e.source_kind for e in corroborating],
                    "corroborating_count": len(corroborating),
                    "context_sources": [e.source_kind for e in context_only],
                    "not_reported_sources": [e.source_kind for e in missing],
                    "explanation": (
                        f"{len(corroborating)} independent source(s) exceeded their "
                        f"own baseline in {alert.cluster} during {alert.week_label}, "
                        "and the deterministic safety engine returned "
                        f"{alert.safety_verdict}."
                    ),
                },
                "evidence": AlertEvidenceSerializer(evidence, many=True).data,
                "cross_level": {
                    "verdict": alert.cross_level_verdict,
                    "statement": alert.cross_level_statement,
                },
                "safety_check": (
                    SafetyCheckSerializer(safety_check).data if safety_check else None
                ),
                "agent_trace": [
                    {
                        "sequence": run.sequence,
                        "stage": run.stage,
                        "agent": run.agent_name,
                        "layer": run.agent_layer,
                        "status": run.status,
                        "duration_ms": run.duration_ms,
                        "used_llm": run.used_llm,
                        "input_summary": run.input_summary,
                        "output": run.output,
                    }
                    for run in runs
                ],
                "flow": [f"{run.stage} -> {run.agent_name}" for run in runs],
                "human_review": {
                    "required": True,
                    "note": (
                        "This alert is a request for human attention with the "
                        "evidence attached. It is not a conclusion and no action "
                        "has been taken."
                    ),
                },
                "data_notice": DATA_NOTICE,
            }
        )


class AlertStatusView(APIView):
    permission_classes = (IsHealthOfficer,)

    def patch(self, request, pk: int):
        alert = generics.get_object_or_404(officer_alert_queryset(request.user), pk=pk)
        serializer = AlertStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        alert.status = data["status"]
        alert.save(update_fields=["status", "updated_at"])

        investigation = None
        if data["status"] in {
            Alert.Status.UNDER_INVESTIGATION,
            Alert.Status.CLOSED,
        }:
            investigation, _ = Investigation.objects.update_or_create(
                alert=alert,
                defaults={
                    "officer": request.user,
                    "status": data.get(
                        "investigation_status",
                        Investigation.Status.UNDER_INVESTIGATION
                        if data["status"] == Alert.Status.UNDER_INVESTIGATION
                        else Investigation.Status.COMPLETED,
                    ),
                    "notes": data.get("notes", ""),
                },
            )

        return Response(
            {
                "alert": AlertListSerializer(alert).data,
                "investigation": (
                    {
                        "status": investigation.status,
                        "officer": request.user.display_name,
                        "notes": investigation.notes,
                    }
                    if investigation
                    else None
                ),
                "note": (
                    "Real-world investigation happens outside this platform, by "
                    "people rather than software."
                ),
            }
        )


class OfficerCommunityDataView(APIView):
    """Consolidated community-level view for the officer's own area.

    Answers "what is being reported and is it moving?" — the broad picture,
    which sits alongside (not instead of) the alert workflow. An alert is what
    the detection and safety pipeline judged worth investigating; this is
    everything that was reported, whether or not it cleared that bar.

    Aggregated counts only. Nothing here touches Patient or PatientAssessment,
    so there is no code path by which an individual record could appear.
    """

    permission_classes = (IsHealthOfficer,)

    PERIOD_OPTIONS = (7, 14, 21)
    DEFAULT_PERIOD = 14

    def get(self, request):
        try:
            days = int(request.query_params.get("period", self.DEFAULT_PERIOD))
        except (TypeError, ValueError):
            days = self.DEFAULT_PERIOD
        if days not in self.PERIOD_OPTIONS:
            days = self.DEFAULT_PERIOD

        today = timezone.localdate()
        (current_start, current_end), (previous_start, previous_end) = period_windows(
            days, today
        )

        reports = scope_queryset(
            CommunityReport.objects.select_related("village", "worker"), request.user
        )

        current_reports = reports.filter(
            period_start__gte=current_start, period_start__lte=current_end
        )
        previous_reports = reports.filter(
            period_start__gte=previous_start, period_start__lte=previous_end
        )
        has_previous = previous_reports.exists()

        current_counts = self._counts_by_category(current_reports)
        previous_counts = self._counts_by_category(previous_reports)

        categories = self._categories(
            current_counts, previous_counts, has_previous, current_reports
        )

        return Response(
            {
                "scope": {
                    "village_code": (
                        request.user.village.code if request.user.village else None
                    ),
                    "village_name": (
                        request.user.village.name if request.user.village else None
                    ),
                    "is_district_wide": scoped_village_id(request.user) is None,
                },
                "period": {
                    "days": days,
                    "options": list(self.PERIOD_OPTIONS),
                    "current": {"start": current_start, "end": current_end},
                    "previous": {"start": previous_start, "end": previous_end},
                    "has_previous_period_data": has_previous,
                },
                "summary": self._summary(categories, has_previous),
                "categories": categories,
                "series": self._series(reports, current_start, current_end, days),
                "recent_observations": self._observations(current_reports),
                "is_empty": not current_reports.exists(),
                "note": (
                    "Reported community health signals. These are observations "
                    "recorded by frontline workers, not confirmed diagnoses."
                ),
                "relationship_note": (
                    "This view shows what is being reported. Alerts show the "
                    "patterns the detection pipeline and safety engine judged "
                    "worth investigating."
                ),
                "data_notice": DATA_NOTICE,
            }
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _counts_by_category(reports) -> dict[str, int]:
        rows = (
            CommunityReportEntry.objects.filter(report__in=reports)
            .values("category")
            .annotate(total=Sum("case_count"))
        )
        return {row["category"]: row["total"] or 0 for row in rows}

    # ------------------------------------------------------------------
    def _categories(
        self, current: dict, previous: dict, has_previous: bool, current_reports
    ) -> list[dict]:
        described = {
            row["category"]: row["n"]
            for row in CommunityReportEntry.objects.filter(
                report__in=current_reports
            )
            .exclude(description="")
            .values("category")
            .annotate(n=Count("id"))
        }

        rows = []
        for category in sorted(set(current) | set(previous)):
            if category in SYSTEM_CATEGORIES:
                continue

            trend = compute_trend(
                current.get(category, 0),
                previous.get(category),
                has_previous_period_data=has_previous
                and category in previous,
            )
            rows.append(
                {
                    "category": category,
                    "label": SignalCategory(category).label,
                    "described_entries": described.get(category, 0),
                    **trend.to_dict(),
                }
            )

        # Busiest first, but anything moving upward floats above the quiet
        # categories so the officer reads the important rows first.
        order = {INCREASING: 0, INSUFFICIENT_DATA: 1, STABLE: 2, DECREASING: 3}
        rows.sort(key=lambda r: (order.get(r["direction"], 9), -r["current"]))
        return rows

    # ------------------------------------------------------------------
    @staticmethod
    def _summary(categories: list[dict], has_previous: bool) -> dict:
        counts = {INCREASING: 0, DECREASING: 0, STABLE: 0, INSUFFICIENT_DATA: 0}
        for row in categories:
            counts[row["direction"]] = counts.get(row["direction"], 0) + 1
        return {
            "increasing": counts[INCREASING],
            "decreasing": counts[DECREASING],
            "stable": counts[STABLE],
            "insufficient_data": counts[INSUFFICIENT_DATA],
            "categories_reported": len(categories),
            "total_current_cases": sum(row["current"] for row in categories),
            "has_previous_period_data": has_previous,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _series(reports, current_start, current_end, days: int) -> dict:
        """Weekly totals for the leading categories, for the chart.

        Covers roughly twice the selected window so the officer can see the
        shape leading into it rather than two bare columns.
        """

        history_start = current_start - dt.timedelta(days=days * 2)
        window = reports.filter(
            period_start__gte=history_start, period_start__lte=current_end
        )

        leaders = list(
            CommunityReportEntry.objects.filter(report__in=window)
            .values("category")
            .annotate(total=Sum("case_count"))
            .order_by("-total")[:5]
        )
        keys = [SignalCategory(row["category"]).label for row in leaders]
        wanted = {row["category"] for row in leaders}

        rows = (
            CommunityReportEntry.objects.filter(
                report__in=window, category__in=wanted
            )
            .values("report__week_label", "category")
            .annotate(total=Sum("case_count"))
            .order_by("report__week_label")
        )

        by_week: dict[str, dict] = {}
        for row in rows:
            week = row["report__week_label"]
            bucket = by_week.setdefault(week, {"week": week})
            label = SignalCategory(row["category"]).label
            bucket[label] = (bucket.get(label) or 0) + (row["total"] or 0)

        points = sorted(by_week.values(), key=lambda p: str(p["week"]))
        for point in points:
            for key in keys:
                point.setdefault(key, 0)

        return {"keys": keys, "points": points}

    # ------------------------------------------------------------------
    @staticmethod
    def _observations(current_reports) -> list[dict]:
        """Workers' written observations — the part a category count can't carry."""

        entries = (
            CommunityReportEntry.objects.filter(report__in=current_reports)
            .exclude(description="")
            .select_related("report", "report__village", "report__worker")
            .order_by("-report__period_start")[:12]
        )
        return [
            {
                "category": entry.category,
                "label": entry.get_category_display(),
                "case_count": entry.case_count,
                "description": entry.description,
                "village_name": entry.report.village.name,
                "worker_name": (
                    entry.report.worker.display_name if entry.report.worker else "—"
                ),
                "week_label": entry.report.week_label,
                "period_start": entry.report.period_start,
                "period_end": entry.report.period_end,
                "unusual_observation": entry.report.unusual_observation,
            }
            for entry in entries
        ]


class OfficerCommunityReportsView(APIView):
    """Community reports submitted by workers in this officer's area.

    Reuses the existing CommunityReport records rather than introducing a
    parallel notification store: 'new' simply means not yet acknowledged.
    Opening the list marks them acknowledged, which is what clears the
    indicator on the dashboard.
    """

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        reports = (
            scope_queryset(
                CommunityReport.objects.select_related("village", "worker"),
                request.user,
            )
            .prefetch_related("entries")
            .order_by("-submitted_at")
        )

        payload = [
            {
                "id": report.id,
                "village_name": report.village.name,
                "village_code": report.village.code,
                "cluster": report.village.cluster,
                "worker_name": report.worker.display_name if report.worker else "—",
                "week_label": report.week_label,
                "period_start": report.period_start,
                "period_end": report.period_end,
                "submitted_at": report.submitted_at,
                "unusual_observation": report.unusual_observation,
                "notes": report.notes,
                "acknowledged": report.acknowledged_at is not None,
                "total_cases": sum(e.case_count for e in report.entries.all()),
                "entries": [
                    {
                        "category": entry.category,
                        "label": entry.get_category_display(),
                        "case_count": entry.case_count,
                        "description": entry.description,
                        "notes": entry.notes,
                    }
                    for entry in report.entries.all()
                    if entry.case_count > 0 or entry.description
                ],
            }
            for report in reports[:60]
        ]

        # Opening the list is the acknowledgement. Done after building the
        # payload so the caller still sees which ones were new.
        reports.filter(acknowledged_at__isnull=True).update(
            acknowledged_at=timezone.now()
        )

        return Response(
            {
                "reports": payload,
                "scope": {
                    "village_name": (
                        request.user.village.name if request.user.village else None
                    ),
                    "is_district_wide": scoped_village_id(request.user) is None,
                },
                "note": (
                    "These are community observations reported by frontline "
                    "workers. Counts are reported cases, not confirmed "
                    "diagnoses."
                ),
                "data_notice": DATA_NOTICE,
            }
        )


class AlertFeedbackView(APIView):
    """Stage 6 — the officer records what was actually found."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        alert = generics.get_object_or_404(officer_alert_queryset(request.user), pk=pk)
        serializer = FeedbackInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        latency = (timezone.now() - alert.created_at).total_seconds()
        feedback, _ = Feedback.objects.update_or_create(
            alert=alert,
            defaults={
                "officer": request.user,
                "outcome": data["outcome"],
                "notes": data.get("notes", ""),
                "resolution_latency_seconds": latency,
            },
        )

        alert.status = Alert.Status.CLOSED
        alert.save(update_fields=["status", "updated_at"])

        Investigation.objects.update_or_create(
            alert=alert,
            defaults={
                "officer": request.user,
                "status": Investigation.Status.COMPLETED,
                "notes": data.get("notes", ""),
            },
        )

        return Response(
            {
                "feedback": FeedbackSerializer(feedback).data,
                "alert": AlertListSerializer(alert).data,
                "meaning": {
                    "VALID_SIGNAL": (
                        "A human confirmed the alert was worth raising. This is "
                        "not confirmation of any disease or outbreak."
                    ),
                    "FALSE_ALERT": (
                        "Investigation found no meaningful underlying pattern. "
                        "Reviewed for threshold or data-quality adjustment."
                    ),
                    "RESOLVED": (
                        "The situation was addressed or explained and needs no "
                        "further action."
                    ),
                }[data["outcome"]],
            },
            status=status.HTTP_201_CREATED,
        )
