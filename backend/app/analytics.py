"""Derived signals computed from stored snapshots.

Deliberately computed on read rather than stored: the rules are a few
comparisons, and keeping them derived means refining a rule never requires
re-ingesting the archive.
"""

from __future__ import annotations

LONG_BUILD_UP = "Long Build Up"
SHORT_BUILD_UP = "Short Build Up"
SHORT_COVERING = "Short Covering"
LONG_UNWINDING = "Long Unwinding"
NEUTRAL = "Neutral"


def interpret_oi(oi_change: float | None, price_change: float | None) -> str:
    """The standard OI/price four-quadrant reading.

        OI up   + price up   -> longs being added
        OI up   + price down -> shorts being added
        OI down + price up   -> shorts closing out
        OI down + price down -> longs closing out

    Either input being flat (or unknown) is not one of the four cases, so it
    reports Neutral rather than being forced into a quadrant.
    """
    if oi_change is None or price_change is None:
        return NEUTRAL
    if oi_change == 0 or price_change == 0:
        return NEUTRAL

    if oi_change > 0:
        return LONG_BUILD_UP if price_change > 0 else SHORT_BUILD_UP
    return SHORT_COVERING if price_change > 0 else LONG_UNWINDING


def direction(value: float | None) -> str:
    """Sign as a display token: 'up', 'down' or 'flat'."""
    if value is None or value == 0:
        return "flat"
    return "up" if value > 0 else "down"
