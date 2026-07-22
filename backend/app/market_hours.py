"""NSE session timing, in IST."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
CLOSE = time(15, 30)

# NSE trading holidays. Must be topped up each year — an out-of-date list
# only causes wasted polls that return stale data, not corruption.
HOLIDAYS_2026: set[date] = set()


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS_2026


def is_market_open(at: datetime | None = None) -> bool:
    at = at or now_ist()
    at = at.astimezone(IST)
    return is_trading_day(at.date()) and OPEN <= at.time() <= CLOSE


def next_tick(interval_seconds: int, at: datetime | None = None) -> datetime:
    """The next wall-clock boundary that is a multiple of the interval.

    Aligning to boundaries (rather than sleeping a fixed delay) keeps
    snapshots landing on tidy 09:15:00, 09:20:00 … marks, so time buckets
    contain exactly one snapshot each.
    """
    at = (at or now_ist()).astimezone(IST)
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((at - midnight).total_seconds())
    return midnight + timedelta(seconds=((elapsed // interval_seconds) + 1) * interval_seconds)
