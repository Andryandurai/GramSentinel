"""Platform-level administrator overview.

One endpoint, one query parameter:

    GET /api/admin/overview/            all villages combined
    GET /api/admin/overview/?village=KVL   one village only

Everything here is read-only and derived from records that already exist —
no new models, no new logging system, no schema change. Village association is
read from the foreign keys the project already has on Patient, Assessment,
CommunityReport, CommunitySignal, Alert and User.

This view is the *only* place that crosses village boundaries, and it is
gated on IsPlatformAdmin. Worker and officer scoping (users/scoping.py) is
untouched.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import Count, Q, Sum
from rest_framework.response import Response
from rest_framework.views import APIView

from alerts.models import Alert, Feedback, Investigation
from assessments.models import PatientAssessment
from community.models import (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
)
from core.constants import DATA_NOTICE, SYSTEM_CATEGORIES, SignalCategory, village_label
from core.models import Village
from patients.models import Patient
from users.models import User
from users.permissions import IsPlatformAdmin
from users.serializers import StaffProfileSerializer

ALL = "all"
RECENT_ACTIVITY_LIMIT = 25
TREND_WEEKS = 6


class InvalidVillageFilter(ValueError):
    pass


def _resolve_village(raw: str | None) -> Village | None:
    """Map the query parameter to a village, or None for 'all'.

    Accepts the village code (KVL) or the demonstration label in either form
    ('village_a', 'Village A'), so the filter is forgiving about how the
    frontend spells it.
    """

    if raw is None or not raw.strip() or raw.strip().lower() == ALL:
        return None

    token = raw.strip()
    village = Village.objects.filter(code__iexact=token).first()
    if village:
        return village

    normalised = token.lower().replace("_", " ").replace("-", " ").strip()
    for code, label in (
        (v.code, village_label(v.code, v.name)) for v in Village.objects.all()
    ):
        if label.lower() == normalised:
            return Village.objects.get(code=code)

    raise InvalidVillageFilter(f"Unknown village filter '{raw}'.")


def _village_payload(village: Village) -> dict[str, Any]:
    return {
        "code": village.code,
        "label": village_label(village.code, village.name),
        "name": village.name,
        "cluster": village.cluster,
    }


def _status_for(active: int, investigating: int) -> str:
    """A one-word state for the village summary table."""

    if investigating:
        return "Under investigation"
    if active:
        return "Monitoring"
    return "Normal"


class AdminOverviewView(APIView):
    permission_classes = (IsPlatformAdmin,)

    def get(self, request):
        try:
            village = _resolve_village(request.query_params.get("village"))
        except InvalidVillageFilter as exc:
            return Response(
                {
                    "error": True,
                    "detail": str(exc),
                    "villages": [
                        _village_payload(v) for v in Village.objects.all()
                    ],
                },
                status=400,
            )

        villages = list(Village.objects.all().order_by("code"))
        scope_ids = [village.id] if village else [v.id for v in villages]

        # Every queryset below is filtered by the same village set, so no
        # section can disagree with another about what is in scope.
        patients = Patient.objects.filter(village_id__in=scope_ids)
        assessments = PatientAssessment.objects.filter(
            village_id__in=scope_ids, is_draft=False
        )
        reports = CommunityReport.objects.filter(village_id__in=scope_ids)
        signals = CommunitySignal.objects.filter(village_id__in=scope_ids)
        alerts = Alert.objects.filter(village_id__in=scope_ids)
        staff = User.objects.filter(village_id__in=scope_ids)

        return Response(
            {
                "scope": {
                    "mode": "village" if village else ALL,
                    "village": _village_payload(village) if village else None,
                    "label": (
                        village_label(village.code, village.name)
                        if village
                        else "All Villages"
                    ),
                    "village_count": len(scope_ids),
                },
                "villages": [_village_payload(v) for v in villages],
                "totals": self._totals(
                    patients, assessments, reports, signals, alerts, staff
                ),
                "village_summary": self._village_summary(villages, village),
                "signal_categories": self._signal_categories(reports),
                "trend": self._trend(villages, village),
                "alerts": self._alerts(alerts),
                "team": self._team(villages, village),
                "recent_activity": self._recent_activity(
                    assessments, reports, alerts, scope_ids
                ),
                "is_empty": not any(
                    [
                        patients.exists(),
                        assessments.exists(),
                        reports.exists(),
                        alerts.exists(),
                    ]
                ),
                "signal_note": (
                    "Counts are reported community health signals, not "
                    "confirmed diagnoses."
                ),
                "data_notice": DATA_NOTICE,
            }
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _totals(patients, assessments, reports, signals, alerts, staff) -> dict:
        outcomes = dict(
            Feedback.objects.filter(alert__in=alerts)
            .values_list("outcome")
            .annotate(n=Count("id"))
        )
        reported_cases = (
            CommunityReportEntry.objects.filter(report__in=reports).aggregate(
                total=Sum("case_count")
            )["total"]
            or 0
        )

        return {
            "patients": patients.count(),
            "assessments": assessments.count(),
            "urgent_assessments": assessments.filter(triage_level="URGENT").count(),
            "community_reports": reports.count(),
            "reported_cases": reported_cases,
            "signals": signals.filter(is_reported=True).count(),
            "workers": staff.filter(role=User.Role.CHW_PHC_WORKER).count(),
            "officers": staff.filter(role=User.Role.HEALTH_OFFICER).count(),
            "alerts_total": alerts.count(),
            "alerts_active": alerts.exclude(status=Alert.Status.CLOSED).count(),
            "alerts_under_investigation": alerts.filter(
                status=Alert.Status.UNDER_INVESTIGATION
            ).count(),
            "alerts_resolved": alerts.filter(status=Alert.Status.CLOSED).count(),
            "alerts_high_severity": alerts.exclude(status=Alert.Status.CLOSED)
            .filter(severity=Alert.Severity.HIGH)
            .count(),
            "investigations": Investigation.objects.filter(alert__in=alerts).count(),
            "outcome_valid_signal": outcomes.get("VALID_SIGNAL", 0),
            "outcome_false_alert": outcomes.get("FALSE_ALERT", 0),
            "outcome_resolved": outcomes.get("RESOLVED", 0),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _village_summary(villages, selected: Village | None) -> list[dict]:
        """Per-village comparison. Narrowed to one row when a village is picked."""

        wanted = [selected] if selected else villages
        rows = []
        for village in wanted:
            alerts = Alert.objects.filter(village=village)
            active = alerts.exclude(status=Alert.Status.CLOSED).count()
            investigating = alerts.filter(
                status=Alert.Status.UNDER_INVESTIGATION
            ).count()
            rows.append(
                {
                    **_village_payload(village),
                    "patients": Patient.objects.filter(village=village).count(),
                    "assessments": PatientAssessment.objects.filter(
                        village=village, is_draft=False
                    ).count(),
                    "community_reports": CommunityReport.objects.filter(
                        village=village
                    ).count(),
                    "active_alerts": active,
                    "under_investigation": investigating,
                    "resolved_alerts": alerts.filter(
                        status=Alert.Status.CLOSED
                    ).count(),
                    "workers": User.objects.filter(
                        village=village, role=User.Role.CHW_PHC_WORKER
                    ).count(),
                    "officers": User.objects.filter(
                        village=village, role=User.Role.HEALTH_OFFICER
                    ).count(),
                    "status": _status_for(active, investigating),
                }
            )
        return rows

    # ------------------------------------------------------------------
    @staticmethod
    def _signal_categories(reports) -> list[dict]:
        """Reported cases by category, across the expanded vocabulary.

        Built from CommunityReportEntry because those are all measured in the
        same unit (reported cases). Summing raw CommunitySignal values would
        add pharmacy units to school percentages.
        """

        rows = (
            CommunityReportEntry.objects.filter(report__in=reports)
            .values("category")
            .annotate(
                reported_cases=Sum("case_count"),
                entries=Count("id"),
                described=Count("id", filter=~Q(description="")),
            )
            .order_by("-reported_cases")
        )

        return [
            {
                "category": row["category"],
                "label": SignalCategory(row["category"]).label,
                "reported_cases": row["reported_cases"] or 0,
                "entries": row["entries"],
                "described": row["described"],
            }
            for row in rows
            if row["category"] not in SYSTEM_CATEGORIES
        ]

    # ------------------------------------------------------------------
    @staticmethod
    def _trend(villages, selected: Village | None) -> dict:
        """Weekly reported cases.

        One line per village when comparing all of them; one line per leading
        category when a single village is selected.
        """

        if selected is None:
            keys = [village_label(v.code, v.name) for v in villages]
            rows = (
                CommunityReportEntry.objects.values(
                    "report__week_label", "report__village__code"
                )
                .annotate(total=Sum("case_count"))
                .order_by("report__week_label")
            )
            by_week: dict[str, dict[str, Any]] = {}
            for row in rows:
                week = row["report__week_label"]
                bucket = by_week.setdefault(week, {"week": week})
                label = village_label(row["report__village__code"], "")
                bucket[label] = (bucket.get(label) or 0) + (row["total"] or 0)
        else:
            top = (
                CommunityReportEntry.objects.filter(report__village=selected)
                .values("category")
                .annotate(total=Sum("case_count"))
                .order_by("-total")[:5]
            )
            keys = [SignalCategory(row["category"]).label for row in top]
            wanted = {row["category"] for row in top}
            rows = (
                CommunityReportEntry.objects.filter(
                    report__village=selected, category__in=wanted
                )
                .values("report__week_label", "category")
                .annotate(total=Sum("case_count"))
                .order_by("report__week_label")
            )
            by_week = {}
            for row in rows:
                week = row["report__week_label"]
                bucket = by_week.setdefault(week, {"week": week})
                label = SignalCategory(row["category"]).label
                bucket[label] = (bucket.get(label) or 0) + (row["total"] or 0)

        points = sorted(by_week.values(), key=lambda p: str(p["week"]))[-TREND_WEEKS:]
        # Fill gaps so Recharts does not draw misleading breaks.
        for point in points:
            for key in keys:
                point.setdefault(key, 0)

        return {"keys": keys, "points": points}

    # ------------------------------------------------------------------
    @staticmethod
    def _alerts(alerts) -> list[dict]:
        rows = alerts.select_related("village").prefetch_related(
            "feedback", "evidence", "safety_checks"
        ).order_by("-created_at")[:20]

        payload = []
        for alert in rows:
            corroborating = [e for e in alert.evidence.all() if e.is_corroborating]
            feedback = getattr(alert, "feedback", None)
            payload.append(
                {
                    "id": alert.id,
                    "title": alert.title,
                    "village_code": alert.village.code,
                    "village_label": village_label(
                        alert.village.code, alert.village.name
                    ),
                    "category": alert.category,
                    "category_label": SignalCategory(alert.category).label,
                    "week_label": alert.week_label,
                    "severity": alert.severity,
                    "status": alert.status,
                    "confidence": alert.confidence,
                    "safety_verdict": alert.safety_verdict,
                    "safety_status": alert.safety_status,
                    "corroborating_source_count": alert.corroborating_source_count,
                    "evidence_summary": ", ".join(
                        sorted(e.source_kind for e in corroborating)
                    )
                    or "—",
                    "cross_level_verdict": alert.cross_level_verdict,
                    "outcome": feedback.outcome if feedback else None,
                    "created_at": alert.created_at,
                }
            )
        return payload

    # ------------------------------------------------------------------
    @staticmethod
    def _team(villages, selected: Village | None) -> list[dict]:
        """Assigned worker(s) and officer(s) per village in scope.

        Each entry now carries that person's professional profile — the same
        fields they maintain themselves — so the administrator can see who is
        assigned where without a second user-management surface. `username` and
        `name` are preserved exactly, so anything already reading this list is
        unaffected.
        """

        wanted = [selected] if selected else villages
        rows = []
        for village in wanted:
            staff = User.objects.filter(
                village=village, is_active=True
            ).select_related("village", "facility")
            rows.append(
                {
                    **_village_payload(village),
                    "workers": [
                        {
                            "username": u.username,
                            "name": u.display_name,
                            **StaffProfileSerializer(u).data,
                        }
                        for u in staff.filter(role=User.Role.CHW_PHC_WORKER)
                    ],
                    "officers": [
                        {
                            "username": u.username,
                            "name": u.display_name,
                            **StaffProfileSerializer(u).data,
                        }
                        for u in staff.filter(role=User.Role.HEALTH_OFFICER)
                    ],
                }
            )
        return rows

    # ------------------------------------------------------------------
    @staticmethod
    def _recent_activity(assessments, reports, alerts, scope_ids) -> list[dict]:
        """Derived from existing timestamped records.

        The project has no general activity log, and adding one for a read-only
        overview would be a heavier change than the feature needs. Instead this
        merges the timestamps already stored on assessments, reports, alerts,
        investigations and feedback.
        """

        events: list[dict[str, Any]] = []

        def add(when: dt.datetime | None, kind: str, code: str, name: str, text: str):
            if when is None:
                return
            events.append(
                {
                    "kind": kind,
                    "village_code": code,
                    "village_label": village_label(code, name),
                    "summary": text,
                    "at": when,
                }
            )

        for row in assessments.select_related("village").order_by("-created_at")[:15]:
            add(
                row.created_at,
                "ASSESSMENT",
                row.village.code,
                row.village.name,
                f"New patient assessment recorded ({row.get_triage_level_display()})",
            )

        for row in reports.select_related("village").order_by("-submitted_at")[:15]:
            add(
                row.submitted_at,
                "COMMUNITY_REPORT",
                row.village.code,
                row.village.name,
                "New community report submitted",
            )

        for row in alerts.select_related("village").order_by("-created_at")[:15]:
            add(
                row.created_at,
                "ALERT",
                row.village.code,
                row.village.name,
                f"New alert generated ({row.severity.lower()}, "
                f"safety {row.safety_verdict.lower()})",
            )

        for row in (
            Investigation.objects.filter(alert__village_id__in=scope_ids)
            .select_related("alert__village")
            .order_by("-updated_at")[:15]
        ):
            add(
                row.updated_at,
                "INVESTIGATION",
                row.alert.village.code,
                row.alert.village.name,
                f"Alert marked {row.get_status_display().lower()}",
            )

        for row in (
            Feedback.objects.filter(alert__village_id__in=scope_ids)
            .select_related("alert__village")
            .order_by("-created_at")[:15]
        ):
            add(
                row.created_at,
                "OUTCOME",
                row.alert.village.code,
                row.alert.village.name,
                f"Alert outcome recorded: {row.get_outcome_display().lower()}",
            )

        events.sort(key=lambda e: e["at"], reverse=True)
        return events[:RECENT_ACTIVITY_LIMIT]
