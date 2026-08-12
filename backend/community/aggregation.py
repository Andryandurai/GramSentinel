"""The aggregation boundary between RuralCare and GramSentinel.

This module is the *only* path by which individual-layer activity reaches the
community layer, and it is deliberately narrow:

    Patient A -> fever
    Patient B -> fever          [ INDIVIDUAL LAYER — RuralCare ]
    Patient C -> fever
              |
              v
      APPROPRIATE AGGREGATION / ANONYMISATION
              |
              v
    "17 fever-related encounters in week 32 in village Kovilur"
              |
              v
          GramSentinel          [ COMMUNITY LAYER — no identifiers ]

What crosses is a count tied to a village, a category and a time window.
Nothing else. No patient id, no name, no assessment id, no free text.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.db.models import Count
from django.utils import timezone

from assessments.models import PatientAssessment
from core.constants import DataQuality, SignalCategory, SourceKind
from core.models import Village

from .models import CommunitySignal, DataSource

logger = logging.getLogger("gramsentinel.aggregation")

#: Fields a community signal may ever carry out of the individual layer.
PERMITTED_AGGREGATE_FIELDS = frozenset(
    {"village_code", "category", "week_label", "encounter_count", "period_start", "period_end"}
)

MIN_AGGREGATE_BASELINE = 1.0


def week_label_for(date: dt.date) -> str:
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_bounds(date: dt.date) -> tuple[dt.date, dt.date]:
    start = date - dt.timedelta(days=date.weekday())
    return start, start + dt.timedelta(days=6)


def assert_no_identifiers(payload: dict) -> None:
    """Guard rail: refuse to emit anything outside the permitted field set.

    Cheap to run, and it turns 'we promise not to leak identifiers' into
    something a test can actually assert.
    """

    leaked = set(payload) - PERMITTED_AGGREGATE_FIELDS
    if leaked:
        raise ValueError(
            f"Aggregation boundary violation: disallowed fields {sorted(leaked)}"
        )


def get_or_create_ruralcare_source(village: Village) -> DataSource:
    source, _ = DataSource.objects.get_or_create(
        code=f"RC-AGG-{village.code}",
        defaults={
            "name": f"Aggregated RuralCare signal — {village.name}",
            "kind": SourceKind.RURALCARE_AGGREGATE,
            "channel": DataSource.Channel.INTERNAL,
            "village": village,
            "simulated": True,
        },
    )
    return source


def build_aggregate_payloads(
    village: Village, week_start: dt.date, week_end: dt.date
) -> list[dict]:
    """Turn individual encounters into anonymised counts by category."""

    rows = (
        PatientAssessment.objects.filter(
            village=village,
            is_draft=False,
            encounter_date__gte=week_start,
            encounter_date__lte=week_end,
        )
        .values("primary_category")
        .annotate(encounter_count=Count("id"))
        .order_by("primary_category")
    )

    payloads = []
    for row in rows:
        payload = {
            "village_code": village.code,
            "category": row["primary_category"],
            "week_label": week_label_for(week_start),
            "encounter_count": row["encounter_count"],
            "period_start": week_start.isoformat(),
            "period_end": week_end.isoformat(),
        }
        assert_no_identifiers(payload)
        payloads.append(payload)
    return payloads


def _rolling_baseline(
    source: DataSource, category: str, before: dt.date, weeks: int = 4
) -> float:
    """Each source is compared against its own recent history, not a global norm."""

    previous = (
        CommunitySignal.objects.filter(
            source=source,
            category=category,
            is_reported=True,
            period_start__lt=before,
        )
        .order_by("-period_start")
        .values_list("value", flat=True)[:weeks]
    )
    values = [v for v in previous if v is not None]
    if not values:
        return MIN_AGGREGATE_BASELINE
    return max(sum(values) / len(values), MIN_AGGREGATE_BASELINE)


def aggregate_village_week(
    village: Village, reference_date: dt.date | None = None
) -> list[CommunitySignal]:
    """Fold this village's week of encounters into community signals.

    Idempotent: re-running for the same week updates the existing rows rather
    than double-counting.
    """

    reference_date = reference_date or timezone.localdate()
    week_start, week_end = week_bounds(reference_date)
    label = week_label_for(week_start)
    source = get_or_create_ruralcare_source(village)

    written: list[CommunitySignal] = []
    for payload in build_aggregate_payloads(village, week_start, week_end):
        baseline = _rolling_baseline(source, payload["category"], week_start)
        signal, _ = CommunitySignal.objects.update_or_create(
            source=source,
            category=payload["category"],
            week_label=label,
            defaults={
                "village": village,
                "period_start": week_start,
                "period_end": week_end,
                "value": float(payload["encounter_count"]),
                "baseline": baseline,
                "unit": "encounters",
                "is_reported": True,
                "data_quality": DataQuality.GOOD,
                "metadata": {
                    "origin": "privacy_preserving_aggregation",
                    "note": (
                        "Anonymised count of RuralCare encounters. No patient "
                        "identifiers cross this boundary."
                    ),
                },
            },
        )
        written.append(signal)

    PatientAssessment.objects.filter(
        village=village,
        is_draft=False,
        encounter_date__gte=week_start,
        encounter_date__lte=week_end,
        aggregated_at__isnull=True,
    ).update(aggregated_at=timezone.now())

    logger.info(
        "[AGGREGATION] %s %s -> %d anonymised community signal(s)",
        village.code,
        label,
        len(written),
    )
    return written


def aggregated_individual_snapshot(village: Village, week_label: str) -> dict:
    """Read side: what the Cross-Level agent is allowed to see from RuralCare."""

    source = get_or_create_ruralcare_source(village)
    signals = CommunitySignal.objects.filter(
        source=source, week_label=week_label, is_reported=True
    )
    return {
        "village_code": village.code,
        "week_label": week_label,
        "counts_by_category": {
            s.category: int(s.value or 0) for s in signals
        },
        "baselines_by_category": {
            s.category: s.baseline for s in signals
        },
    }


def category_for_symptoms(symptoms: list[str]) -> str:
    """Map a normalised symptom set to the community signal category it feeds."""

    symptom_set = {s.lower() for s in symptoms}
    if symptom_set & {"fever", "chills", "rigors", "high_fever"}:
        return SignalCategory.FEVER
    if symptom_set & {"cough", "breathlessness", "sore_throat", "chest_pain"}:
        return SignalCategory.RESPIRATORY
    if symptom_set & {"diarrhoea", "vomiting", "abdominal_pain", "dehydration"}:
        return SignalCategory.DIARRHOEAL
    return SignalCategory.OTHER
