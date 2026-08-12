"""Stage 1 — Data Ingestion.

Validation, normalisation to common units and categories, timestamp alignment,
location mapping, deduplication, and explicit missing-data flagging.

The rule that matters most here: a source that did not submit is recorded as
"not submitted", never as "zero". Treating absence as a value is one of the
easiest ways for a surveillance system to produce a confident and completely
wrong answer.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.db import transaction

from community.models import CommunitySignal, DataSource
from core.constants import DataQuality, SignalCategory, SourceKind
from core.models import Village

from .models import IngestionEvent

logger = logging.getLogger("gramsentinel.ingestion")

VALID_CATEGORIES = {c.value for c in SignalCategory}
VALID_KINDS = {k.value for k in SourceKind}

#: Units each source kind is normalised to before any agent sees it.
CANONICAL_UNITS = {
    SourceKind.CHW: "reports",
    SourceKind.PHC: "encounters",
    SourceKind.PHARMACY: "units",
    SourceKind.SCHOOL: "%",
    SourceKind.WEATHER: "mm",
    SourceKind.LAB: "confirmations",
    SourceKind.RURALCARE_AGGREGATE: "encounters",
}


class ValidationError(ValueError):
    """A record that cannot be safely normalised is rejected, not guessed at."""


def week_bounds_from_label(label: str) -> tuple[dt.date, dt.date]:
    """'2026-W32' -> (Monday, Sunday) of that ISO week."""

    try:
        year_part, week_part = label.split("-W")
        start = dt.date.fromisocalendar(int(year_part), int(week_part), 1)
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"Unparseable week label {label!r}") from exc
    return start, start + dt.timedelta(days=6)


def validate_record(record: dict[str, Any]) -> list[str]:
    """Return a list of problems. Empty means the record is usable."""

    problems: list[str] = []

    if record.get("source_code") in (None, ""):
        problems.append("missing source_code")
    if record.get("category") not in VALID_CATEGORIES:
        problems.append(f"unknown category {record.get('category')!r}")
    if not record.get("week_label"):
        problems.append("missing week_label")

    is_reported = record.get("is_reported", True)
    value = record.get("value")

    if is_reported:
        if value is None:
            problems.append("reported record has no value")
        else:
            try:
                float(value)
            except (TypeError, ValueError):
                problems.append(f"non-numeric value {value!r}")
    elif value is not None:
        # This is the integrity guarantee behind Safety Rule 8.
        problems.append(
            "record marked not-reported but carries a value; missing data must "
            "not be given a number"
        )

    return problems


def normalise_record(record: dict[str, Any], source: DataSource) -> dict[str, Any]:
    period_start, period_end = week_bounds_from_label(record["week_label"])
    is_reported = bool(record.get("is_reported", True))

    quality = record.get("data_quality") or DataQuality.GOOD
    if not is_reported:
        quality = DataQuality.MISSING

    return {
        "source": source,
        "village": source.village,
        "category": record["category"],
        "week_label": record["week_label"],
        "period_start": period_start,
        "period_end": period_end,
        "value": float(record["value"]) if is_reported and record.get("value") is not None else None,
        "baseline": float(record["baseline"]) if record.get("baseline") is not None else None,
        "unit": record.get("unit") or CANONICAL_UNITS.get(source.kind, ""),
        "is_reported": is_reported,
        "data_quality": quality,
        "metadata": record.get("metadata") or {},
    }


@transaction.atomic
def ingest_batch(
    records: list[dict[str, Any]],
    *,
    channel: str = DataSource.Channel.PORTAL,
    week_label: str = "",
) -> IngestionEvent:
    """Validate, normalise, deduplicate and store a batch of source records.

    Deduplication is by (source, category, week_label): re-submitting the same
    window updates the existing row rather than creating a second one.
    """

    received = len(records)
    accepted = rejected = deduplicated = missing = 0
    notes: list[str] = []
    last_source: DataSource | None = None

    for record in records:
        problems = validate_record(record)
        if problems:
            rejected += 1
            notes.append(
                {
                    "source_code": record.get("source_code"),
                    "week_label": record.get("week_label"),
                    "rejected_because": problems,
                }
            )
            continue

        try:
            source = DataSource.objects.get(code=record["source_code"])
        except DataSource.DoesNotExist:
            rejected += 1
            notes.append(
                {
                    "source_code": record.get("source_code"),
                    "rejected_because": ["unregistered data source"],
                }
            )
            continue

        last_source = source
        payload = normalise_record(record, source)
        if not payload["is_reported"]:
            missing += 1

        existed = CommunitySignal.objects.filter(
            source=source,
            category=payload["category"],
            week_label=payload["week_label"],
        ).exists()
        if existed:
            deduplicated += 1

        CommunitySignal.objects.update_or_create(
            source=source,
            category=payload["category"],
            week_label=payload["week_label"],
            defaults=payload,
        )
        accepted += 1

    if rejected and accepted:
        result = IngestionEvent.Result.PARTIAL
    elif rejected:
        result = IngestionEvent.Result.REJECTED
    else:
        result = IngestionEvent.Result.ACCEPTED

    event = IngestionEvent.objects.create(
        source=last_source,
        channel=channel,
        week_label=week_label or (records[0].get("week_label", "") if records else ""),
        records_received=received,
        records_accepted=accepted,
        records_rejected=rejected,
        records_deduplicated=deduplicated,
        missing_flagged=missing,
        result=result,
        validation_notes=notes,
        simulated=True,
    )

    logger.info(
        "[STAGE 1 INGESTION] %s: %d received, %d accepted, %d rejected, "
        "%d deduplicated, %d flagged missing",
        channel,
        received,
        accepted,
        rejected,
        deduplicated,
        missing,
    )
    return event


def build_agent_payloads(
    village: Village, week_label: str, category: str
) -> list[dict[str, Any]]:
    """Assemble the per-source payloads the community agents consume.

    Sources registered for this village but with nothing stored for the window
    are emitted explicitly as not-reported, so a silent gap becomes a visible
    'missing' card rather than disappearing from the evidence set.
    """

    period_start, period_end = week_bounds_from_label(week_label)
    relevant_categories = {category, SignalCategory.ENVIRONMENT, SignalCategory.LAB_CONFIRMATION}

    stored = {
        (s.source_id, s.category): s
        for s in CommunitySignal.objects.filter(
            village=village, week_label=week_label, category__in=relevant_categories
        ).select_related("source")
    }

    payloads: list[dict[str, Any]] = []
    for source in DataSource.objects.filter(village=village, is_active=True):
        if source.kind == SourceKind.RURALCARE_AGGREGATE:
            continue  # consumed by the Cross-Level agent, not a signal agent

        if source.kind == SourceKind.WEATHER:
            wanted = SignalCategory.ENVIRONMENT
        elif source.kind == SourceKind.LAB:
            wanted = SignalCategory.LAB_CONFIRMATION
        else:
            wanted = category

        signal = stored.get((source.id, wanted))
        base = {
            "source_kind": source.kind,
            "source_name": source.name,
            "category": wanted,
            "village_code": village.code,
            "village_name": village.name,
            "cluster": village.cluster,
            "week_label": week_label,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "unit": CANONICAL_UNITS.get(source.kind, ""),
        }

        if signal is None:
            payloads.append(
                {**base, "value": None, "baseline": None, "is_reported": False,
                 "data_quality": DataQuality.MISSING}
            )
            continue

        payloads.append(
            {
                **base,
                "value": signal.value,
                "baseline": signal.baseline,
                "is_reported": signal.is_reported,
                "data_quality": signal.data_quality,
                "period_start": signal.period_start.isoformat(),
                "period_end": signal.period_end.isoformat(),
                "unit": signal.unit or base["unit"],
                **signal.metadata,
            }
        )

    return payloads
