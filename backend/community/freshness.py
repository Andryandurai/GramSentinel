"""Source freshness — how recent each evidence stream actually is.

The question this answers for a health officer is narrow and important: *when
did this source last tell us anything?* An officer comparing a CHW report from
twenty minutes ago against a laboratory feed that has been silent for four days
is not looking at two equally reliable pieces of evidence, and nothing else in
the platform says so out loud.

Two rules govern everything here:

1. **Missing stays missing.** A source that sent nothing for the current
   reporting period is reported as MISSING with `value=None`. It is never
   rendered as zero, never averaged in, and never quietly dropped from a list
   so that its absence stops being visible (Safety Engine R8).

2. **Freshness is informational.** Nothing in this module feeds the Safety
   Engine, alert severity, confidence, or the corroborating-source count. A
   stale source does not downgrade an alert; it tells the human reading the
   alert what they are looking at. Wiring freshness into severity is a
   deliberate future decision with its own safety review, not a side effect of
   displaying it.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from core.constants import FreshnessStatus, freshness_thresholds

from .models import CommunitySignal, DataSource


def humanise_age(delta: dt.timedelta) -> str:
    """'20 minutes ago' / '3 hours ago' / '4 days ago'.

    Coarse by design. An officer deciding whether to trust a source needs the
    order of magnitude, and a precise-looking "3h 47m ago" invites more
    confidence in the number than a device-to-server timestamp chain deserves.
    """

    seconds = int(delta.total_seconds())
    if seconds < 0:
        # A source clock running ahead of the server. Saying "in 4 minutes"
        # would be nonsense to read, and treating it as stale would be wrong.
        return "just now"
    if seconds < 90:
        return "just now"

    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes ago"

    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"

    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def classify(
    last_report_at: dt.datetime | None,
    *,
    source_kind: str,
    reported_this_period: bool,
    now: dt.datetime | None = None,
) -> tuple[str, str]:
    """Return (status, human explanation) for one source.

    MISSING is checked before any age comparison. "Nothing arrived for the
    period we are currently reporting on" is a different statement from "the
    last thing that arrived is old", and it is the one an officer must not
    misread — so it wins whenever both are true.
    """

    now = now or timezone.now()

    if last_report_at is None:
        return (
            FreshnessStatus.MISSING,
            "No data has ever been received from this source.",
        )

    age = now - last_report_at
    age_text = humanise_age(age)

    if not reported_this_period:
        return (
            FreshnessStatus.MISSING,
            f"No report this period. Last successful update {age_text}.",
        )

    fresh_max, aging_max = freshness_thresholds(source_kind)
    hours = age.total_seconds() / 3600.0

    if hours <= fresh_max:
        return FreshnessStatus.FRESH, f"Updated {age_text}."
    if hours <= aging_max:
        return (
            FreshnessStatus.AGING,
            f"Updated {age_text} — this source is becoming out of date.",
        )
    return (
        FreshnessStatus.STALE,
        f"Updated {age_text} — treat this source as out of date.",
    )


def describe_source(
    source: DataSource,
    *,
    reported_this_period: bool,
    now: dt.datetime | None = None,
) -> dict:
    """The freshness payload for one source, as the portal renders it."""

    now = now or timezone.now()
    status, explanation = classify(
        source.last_report_at,
        source_kind=source.kind,
        reported_this_period=reported_this_period,
        now=now,
    )

    return {
        "source_id": source.id,
        "source_code": source.code,
        "source_name": source.name,
        "source_kind": source.kind,
        "source_kind_display": source.get_kind_display(),
        "village_code": source.village.code,
        "village_name": source.village.name,
        "channel": source.channel,
        "status": status,
        "status_display": FreshnessStatus(status).label,
        "last_report_at": source.last_report_at,
        "age_text": (
            humanise_age(now - source.last_report_at)
            if source.last_report_at
            else None
        ),
        "reported_this_period": reported_this_period,
        "explanation": explanation,
        # Never a number. A consumer that wants to show "how much did this
        # source report" must read the signals; freshness deliberately carries
        # no value so it cannot be mistaken for one.
        "value": None,
    }


def sources_reporting_in(week_label: str, sources: list[DataSource]) -> set[int]:
    """Ids of the given sources that have a reported signal for `week_label`."""

    if not sources:
        return set()
    return set(
        CommunitySignal.objects.filter(
            source__in=sources, week_label=week_label, is_reported=True
        )
        .values_list("source_id", flat=True)
        .distinct()
    )


def freshness_report(
    sources: list[DataSource],
    *,
    week_label: str,
    now: dt.datetime | None = None,
) -> list[dict]:
    """Freshness for a set of sources, worst first.

    Ordered so the sources an officer most needs to notice — the silent ones —
    are at the top rather than buried under the healthy feeds.
    """

    now = now or timezone.now()
    reporting = sources_reporting_in(week_label, sources)

    rows = [
        describe_source(
            source, reported_this_period=source.id in reporting, now=now
        )
        for source in sources
    ]

    severity = {
        FreshnessStatus.MISSING: 0,
        FreshnessStatus.STALE: 1,
        FreshnessStatus.AGING: 2,
        FreshnessStatus.FRESH: 3,
    }
    rows.sort(key=lambda row: (severity[row["status"]], row["source_name"]))
    return rows


def summarise(rows: list[dict]) -> dict:
    """Counts per status, for the panel header."""

    counts = {status.value: 0 for status in FreshnessStatus}
    for row in rows:
        counts[row["status"]] += 1
    return {
        "total_sources": len(rows),
        "fresh": counts[FreshnessStatus.FRESH],
        "aging": counts[FreshnessStatus.AGING],
        "stale": counts[FreshnessStatus.STALE],
        "missing": counts[FreshnessStatus.MISSING],
        "needs_attention": counts[FreshnessStatus.STALE]
        + counts[FreshnessStatus.MISSING],
    }


def freshness_by_village_kind(
    sources: list[DataSource],
    *,
    week_label: str,
    now: dt.datetime | None = None,
) -> dict[tuple[str, str], dict]:
    """Freshness keyed by (village_code, source_kind).

    Built once per request so attaching freshness to a set of alert evidence
    cards is a dict lookup rather than a query per card.
    """

    return {
        (row["village_code"], row["source_kind"]): row
        for row in freshness_report(sources, week_label=week_label, now=now)
    }
