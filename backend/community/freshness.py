"""Source Freshness Indicator.

Answers one question for a Health Officer: "how recently did this source
last actually report?" — nothing else. It is purely informational.

    Fresh   = recent
    Aging   = becoming old
    Stale   = old
    Missing = no report received

This module never reads or writes anything on `safety/engine.py`, never
changes an `Alert`'s severity/verdict, and is not consulted by the
deterministic Safety Engine in either direction. Freshness and safety are
two separate questions about two separate things: freshness describes a
`CommunitySignal`'s age; safety decides whether a *pattern across sources*
is corroborated enough to raise for human review. Conflating the two would
mean either treating old evidence as automatically unsafe (it might still be
the only evidence there is) or treating fresh evidence as automatically safe
(recency says nothing about corroboration) — this module deliberately does
neither.

Derived entirely from existing, already-persisted data: `CommunitySignal.
ingested_at` (Section 1D of the task this module implements: "prefer
deriving freshness from existing persisted source/report records"). No new
model was introduced.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from core.constants import FreshnessStatus, SourceKind

from .models import CommunitySignal

#: The six source kinds an officer's freshness view covers. RURALCARE_AGGREGATE
#: is deliberately excluded: `integrations/ingestion.py::build_agent_payloads()`
#: never routes it through a Signal Agent or into an `AlertEvidence` card — it
#: is consumed only internally by the Cross-Level Intelligence agent as an
#: agreement check, so it is not "a source/evidence input" in the sense this
#: feature covers (Section 1C of the task).
FRESHNESS_SOURCE_KINDS: tuple[str, ...] = (
    SourceKind.CHW,
    SourceKind.PHC,
    SourceKind.PHARMACY,
    SourceKind.SCHOOL,
    SourceKind.WEATHER,
    SourceKind.LAB,
)


def _thresholds() -> tuple[float, float]:
    hours = settings.GRAMSENTINEL.get("FRESHNESS_THRESHOLDS_HOURS", {})
    return float(hours.get("FRESH", 24)), float(hours.get("AGING", 72))


def _relative_time(delta: dt.timedelta) -> str:
    """'20 minutes ago', '3 hours ago', '2 days ago' — coarse, human-readable."""

    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _status_for_age(delta: dt.timedelta) -> str:
    fresh_hours, aging_hours = _thresholds()
    hours = delta.total_seconds() / 3600.0
    if hours <= fresh_hours:
        return FreshnessStatus.FRESH
    if hours <= aging_hours:
        return FreshnessStatus.AGING
    return FreshnessStatus.STALE


def _card(
    source_kind: str,
    last_signal: CommunitySignal | None,
    reference_time: dt.datetime,
) -> dict:
    if last_signal is None or last_signal.ingested_at is None:
        return {
            "source_kind": source_kind,
            # English-only fields, kept only as a fallback for any caller
            # that hasn't been updated to localize from `source_kind`/
            # `relative_time_seconds` itself (frontend localization task:
            # a display *label* for a finite, backend-owned enum is a UI
            # concern, not persisted user data — the frontend must render
            # its own translated text keyed by the stable `source_kind`/
            # `status` values above, never this string directly).
            "source_label": SourceKind(source_kind).label,
            "status": FreshnessStatus.MISSING,
            "last_updated_at": None,
            "relative_time": "No report this period",
            "relative_time_seconds": None,
            "received": False,
        }

    delta = reference_time - last_signal.ingested_at
    return {
        "source_kind": source_kind,
        "source_label": SourceKind(source_kind).label,
        "status": _status_for_age(delta),
        "last_updated_at": last_signal.ingested_at.isoformat(),
        "relative_time": _relative_time(delta),
        # Raw elapsed seconds — the one value a frontend needs to compute
        # its own locale-aware "N minutes/hours/days ago" string. Never
        # negative (see `_relative_time`'s own clamp).
        "relative_time_seconds": max(0, int(delta.total_seconds())),
        "received": True,
    }


def build_source_freshness(village, *, reference_time: dt.datetime | None = None) -> list[dict]:
    """One freshness card per source kind, for one village.

    "Most recently reported" means the latest `CommunitySignal.ingested_at`
    across any category for that (village, source kind) — a rolling recency
    measure, not a check against one specific calendar week, so a source that
    reported *something* recently reads as fresh even if this exact week's
    figure for one particular category is still pending. Only `is_reported`
    rows are considered: an explicitly-not-reported row (Section 1E — never
    treated as zero) does not count as "the source reported", so it correctly
    falls through to MISSING rather than being read as recent activity.
    """

    if village is None:
        return []

    reference_time = reference_time or timezone.now()

    latest_by_kind = {
        row["source__kind"]: row["latest"]
        for row in (
            CommunitySignal.objects.filter(village=village, is_reported=True)
            .values("source__kind")
            .annotate(latest=Max("ingested_at"))
        )
    }

    cards = []
    for kind in FRESHNESS_SOURCE_KINDS:
        latest_at = latest_by_kind.get(kind)
        if latest_at is None:
            cards.append(_card(kind, None, reference_time))
            continue
        # Re-fetch the actual row so `_card` can report its own timestamp
        # verbatim rather than trusting the aggregate value's tz-handling.
        signal = (
            CommunitySignal.objects.filter(
                village=village, source__kind=kind, is_reported=True, ingested_at=latest_at
            )
            .order_by("-id")
            .first()
        )
        cards.append(_card(kind, signal, reference_time))

    return cards


def freshness_for_source(
    village_code: str, source_kind: str, *, reference_time: dt.datetime | None = None
) -> dict:
    """Same computation as `build_source_freshness`, for one evidence card.

    Keyed on `village_code`/`source_kind` (plain strings) rather than a
    `Village`/`DataSource` instance because that is exactly what
    `AlertEvidence` already stores on each row (Section 1I of the task) —
    no extra join is needed to answer "how fresh was this evidence's source".
    """

    reference_time = reference_time or timezone.now()
    signal = (
        CommunitySignal.objects.filter(
            village__code=village_code, source__kind=source_kind, is_reported=True
        )
        .order_by("-ingested_at")
        .first()
    )
    return _card(source_kind, signal, reference_time)
