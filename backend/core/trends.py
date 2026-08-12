"""Period-over-period trend calculation.

One implementation, shared by anything that needs to say whether a reported
signal is going up, down or holding steady. Kept deliberately simple and
deterministic: the same two numbers always produce the same verdict.

The existing `CommunitySignal.change_pct` compares a single measurement to its
own rolling baseline, which is a different question (is this week unusual for
this source?). This module answers "is this category busier than it was last
period?" across a whole village.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

#: A move smaller than this is noise, not a trend. Chosen so that a change
#: like 9 -> 8 (-11%) still reads as a decrease, while 10 -> 10 does not.
STABLE_THRESHOLD_PCT = 10.0

INCREASING = "INCREASING"
DECREASING = "DECREASING"
STABLE = "STABLE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

DIRECTION_LABELS = {
    INCREASING: "Increasing",
    DECREASING: "Decreasing",
    STABLE: "Stable",
    INSUFFICIENT_DATA: "Insufficient data",
}

DIRECTION_SYMBOLS = {
    INCREASING: "up",
    DECREASING: "down",
    STABLE: "steady",
    INSUFFICIENT_DATA: "unknown",
}


@dataclass(frozen=True)
class Trend:
    current: int
    previous: int | None
    change_pct: float | None
    direction: str
    label: str
    #: True when the previous period had no activity at all, so a percentage
    #: would be a division by zero. The UI shows "new activity" instead of a
    #: made-up number.
    is_new_activity: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "previous": self.previous,
            "change_pct": self.change_pct,
            "direction": self.direction,
            "direction_label": self.label,
            "symbol": DIRECTION_SYMBOLS[self.direction],
            "is_new_activity": self.is_new_activity,
        }


def compute_trend(
    current: int | float | None,
    previous: int | float | None,
    *,
    has_previous_period_data: bool = True,
    stable_threshold: float = STABLE_THRESHOLD_PCT,
) -> Trend:
    """Compare a current period against the one before it.

    `has_previous_period_data` distinguishes "the previous period reported
    zero of this category" from "there is no previous period on record". The
    first is a real decrease; the second is not knowable, and claiming a trend
    there would be wrong.
    """

    current_value = int(current or 0)

    if not has_previous_period_data or previous is None:
        return Trend(
            current=current_value,
            previous=None,
            change_pct=None,
            direction=INSUFFICIENT_DATA,
            label=DIRECTION_LABELS[INSUFFICIENT_DATA],
        )

    previous_value = int(previous or 0)

    if previous_value == 0:
        if current_value == 0:
            return Trend(
                current=0,
                previous=0,
                change_pct=0.0,
                direction=STABLE,
                label=DIRECTION_LABELS[STABLE],
            )
        # Percentage change from zero is undefined; say so rather than
        # inventing +100% or an infinity.
        return Trend(
            current=current_value,
            previous=0,
            change_pct=None,
            direction=INCREASING,
            label=DIRECTION_LABELS[INCREASING],
            is_new_activity=True,
        )

    change_pct = round(
        (current_value - previous_value) / previous_value * 100.0, 1
    )

    if change_pct >= stable_threshold:
        direction = INCREASING
    elif change_pct <= -stable_threshold:
        direction = DECREASING
    else:
        direction = STABLE

    return Trend(
        current=current_value,
        previous=previous_value,
        change_pct=change_pct,
        direction=direction,
        label=DIRECTION_LABELS[direction],
    )


def period_windows(
    days: int, reference: dt.date
) -> tuple[tuple[dt.date, dt.date], tuple[dt.date, dt.date]]:
    """Return ((current_start, current_end), (previous_start, previous_end)).

    Both windows are the same length and do not overlap, so a report can never
    be counted in both.
    """

    current_end = reference
    current_start = reference - dt.timedelta(days=days - 1)
    previous_end = current_start - dt.timedelta(days=1)
    previous_start = previous_end - dt.timedelta(days=days - 1)
    return (current_start, current_end), (previous_start, previous_end)
