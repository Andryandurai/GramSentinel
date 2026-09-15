"""Operational Context — a source-generic, village-generic interpretation
layer sitting between a raw reported measurement and the evidence card a
signal agent produces from it.

    RAW SIGNAL (CommunitySignal, unchanged)
        |
        v
    OPERATIONAL CONTEXT RESOLUTION  (this module)
        |
        v
    SIGNAL INTERPRETATION  (agents/gramsentinel/signal_agents.py)
        |
        v
    EVIDENCE (AlertEvidence, carries an immutable snapshot)
        |
        v
    CORRELATION (alerts/evidence_relationships.py — unchanged)
        |
        v
    DETERMINISTIC SAFETY ENGINE (safety/ — unchanged; sees is_corroborating=False)
        |
        v
    ALERT / INVESTIGATION

Nothing in this module ever reads or writes a `CommunitySignal.value`,
`Alert`, or `SafetyCheck` row — it only answers one question ("is there an
applicable, human-recorded context for this source and this reporting
window?") and, when the answer is yes, describes it as an immutable dict a
caller can attach to an evidence card. This is deliberately the *only*
place that question is answered, so `agents/gramsentinel/signal_agents.py`
never has to special-case a source kind or a village.
"""

from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import DataSource, SourceOperationalContext


def resolve_context(
    source_id: int | None,
    period_start: dt.date,
    period_end: dt.date,
    *,
    as_of: dt.datetime | None = None,
) -> SourceOperationalContext | None:
    """The single applicable context for this source/window, or None.

    Write-time overlap validation (`validate_no_overlap` below) guarantees
    at most one non-cancelled context can ever cover a given date for a
    given source, so "the first match" is never an arbitrary tie-break.
    """

    if source_id is None:
        return None

    as_of = as_of or timezone.now()
    candidates = SourceOperationalContext.objects.filter(
        source_id=source_id, starts_on__lte=period_end, ends_on__gte=period_start
    )
    for candidate in candidates:
        if candidate.is_applicable(period_start, period_end, as_of=as_of):
            return candidate
    return None


def context_snapshot(context: SourceOperationalContext) -> dict:
    """An immutable dict — this, not a foreign key, is what gets persisted
    onto `AlertEvidence.operational_context` (Section 11: historical
    auditability). Reading it back never depends on the
    `SourceOperationalContext` row still existing in its original form."""

    return {
        "id": context.id,
        "mode": context.mode,
        "mode_label": context.get_mode_display(),
        "reason": context.reason,
        "notes": context.notes,
        "starts_on": context.starts_on.isoformat(),
        "ends_on": context.ends_on.isoformat(),
        "source_name": context.source.name,
        "recorded_at": context.created_at.isoformat(),
    }


def validate_no_overlap(
    source: DataSource, starts_on: dt.date, ends_on: dt.date, *, exclude_id: int | None = None
) -> None:
    """Section 19: "Prefer rejecting the conflict... never silently allow
    ambiguous overlapping active contexts." Only non-cancelled contexts can
    conflict — a cancelled one no longer applies going forward, so a new
    context is free to reuse its dates."""

    overlapping = SourceOperationalContext.objects.filter(
        source=source,
        cancelled_at__isnull=True,
        starts_on__lte=ends_on,
        ends_on__gte=starts_on,
    )
    if exclude_id is not None:
        overlapping = overlapping.exclude(id=exclude_id)
    if overlapping.exists():
        existing = overlapping.first()
        raise ValidationError(
            f"This source already has an operational context covering part of "
            f"that period ({existing.starts_on} → {existing.ends_on}, "
            f"\"{existing.reason}\"). Cancel or edit it first."
        )
