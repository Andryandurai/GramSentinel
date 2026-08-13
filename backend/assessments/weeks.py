"""Week options for the worker dashboard's time-period filter.

There is already one definition of a week in this platform — the Monday-to-
Sunday ISO week used by the aggregation boundary and by every community signal
— so this module reuses it rather than introducing a second, conflicting one:

    community.aggregation.week_bounds()      Monday .. Sunday
    community.aggregation.week_label_for()   e.g. "2026-W33"

The stored label is what the API accepts and returns. "Week 1", "Week 2" … are
display numbers assigned in chronological order across the weeks the signed-in
worker actually has data for, so the numbering never depends on hard-coded
dates and never spans a village the user cannot see.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

from community.aggregation import week_bounds, week_label_for

#: Upper bound on how many week options are offered. Only a pathological data
#: range would reach it; it exists so the dropdown cannot grow without limit.
MAX_WEEKS = 52

ALL_WEEKS = "all"


def format_range(start: dt.date, end: dt.date) -> str:
    """'Aug 3 – Aug 9' — readable to a worker, unambiguous across months."""

    return f"{start:%b} {start.day} – {end:%b} {end.day}"


def parse_week_label(label: str) -> tuple[dt.date, dt.date] | None:
    """Turn '2026-W33' into its Monday/Sunday bounds, or None if unusable."""

    if not label:
        return None
    text = str(label).strip().upper()
    if len(text) < 7 or "-W" not in text:
        return None
    year_part, _, week_part = text.partition("-W")
    try:
        year = int(year_part)
        week = int(week_part)
        monday = dt.date.fromisocalendar(year, week, 1)
    except (ValueError, TypeError):
        return None
    return monday, monday + dt.timedelta(days=6)


def build_week_options(dates: Iterable[dt.date | None]) -> list[dict]:
    """Every week between the earliest and latest date supplied, in order.

    Weeks with no data in between are still listed: a worker reading "Week 2"
    should see a real, continuous calendar rather than a numbering that skips.
    An empty week is handled by the dashboard, not hidden here.
    """

    real = sorted({d for d in dates if isinstance(d, dt.date)})
    if not real:
        return []

    first_start, _ = week_bounds(real[0])
    last_start, _ = week_bounds(real[-1])

    starts: list[dt.date] = []
    cursor = first_start
    while cursor <= last_start and len(starts) < MAX_WEEKS:
        starts.append(cursor)
        cursor += dt.timedelta(days=7)

    # If the range is longer than the cap, keep the most recent weeks — those
    # are the ones a worker is realistically looking at.
    if cursor <= last_start:
        starts = []
        cursor = last_start - dt.timedelta(weeks=MAX_WEEKS - 1)
        while cursor <= last_start:
            starts.append(cursor)
            cursor += dt.timedelta(days=7)

    options = []
    for number, start in enumerate(starts, start=1):
        end = start + dt.timedelta(days=6)
        options.append(
            {
                "value": week_label_for(start),
                "number": number,
                "label": f"Week {number}",
                "start": start,
                "end": end,
                "range_label": format_range(start, end),
            }
        )
    return options


def resolve_selection(
    requested: str | None, options: list[dict]
) -> tuple[str, dt.date | None, dt.date | None, dict | None, str]:
    """Work out which period was asked for.

    Returns (selected, start, end, matching option, notice). An unusable value
    falls back to all weeks with a short notice rather than an error page —
    a dashboard should still render.
    """

    value = (requested or "").strip()
    if not value or value.lower() == ALL_WEEKS:
        return ALL_WEEKS, None, None, None, ""

    by_value = {option["value"]: option for option in options}

    # Accept the display number too ("2" for Week 2), since that is what the
    # worker sees on screen.
    if value.isdigit():
        for option in options:
            if option["number"] == int(value):
                return option["value"], option["start"], option["end"], option, ""

    option = by_value.get(value.upper())
    if option:
        return option["value"], option["start"], option["end"], option, ""

    bounds = parse_week_label(value)
    if bounds:
        # A valid week that simply holds no data for this user: honour it and
        # let the empty state do its job.
        start, end = bounds
        return week_label_for(start), start, end, None, ""

    return (
        ALL_WEEKS,
        None,
        None,
        None,
        "That time period could not be read, so all weeks are shown.",
    )
