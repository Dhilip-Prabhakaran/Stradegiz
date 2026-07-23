"""NSE session timing, in IST."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
CLOSE = time(15, 30)

# NSE/BSE equity & derivatives trading holidays.
#
# Sourced from a third-party calendar, NOT an official exchange circular, so
# treat it as advisory. That is precisely why it is never used to decide
# whether to record: see is_market_open below.
#
# Needs topping up each year.
HOLIDAYS_2026: set[date] = {
    date(2026, 1, 15),   # Maharashtra municipal elections
    date(2026, 1, 26),   # Republic Day
    date(2026, 3, 3),    # Holi
    date(2026, 3, 26),   # Shri Ram Navami
    date(2026, 3, 31),   # Shri Mahavir Jayanti
    date(2026, 4, 3),    # Good Friday
    date(2026, 4, 14),   # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 5, 28),   # Bakri Id
    date(2026, 6, 26),   # Muharram
    date(2026, 9, 14),   # Ganesh Chaturthi
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 20),  # Dussehra
    date(2026, 11, 10),  # Diwali - Balipratipada
    date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    date(2026, 12, 25),  # Christmas
}


def is_holiday(d: date) -> bool:
    return d in HOLIDAYS_2026


def now_ist() -> datetime:
    return datetime.now(IST)


def is_trading_day(d: date) -> bool:
    """Whether the exchanges are expected to trade — weekday, not a holiday.

    Used where being wrong is recoverable: skipping a backfill day can simply
    be re-run. Deliberately NOT used to gate live capture.
    """
    return d.weekday() < 5 and not is_holiday(d)


def is_market_open(at: datetime | None = None) -> bool:
    """Whether the recorder should be capturing right now.

    Checks the weekday and session window but deliberately ignores the holiday
    list. The list is advisory, and the two failure modes are wildly
    asymmetric: polling through a holiday wastes a few requests, while wrongly
    skipping a real session loses intraday history that cannot be recovered
    from any source. So the recorder errs towards capturing.
    """
    at = (at or now_ist()).astimezone(IST)
    return at.weekday() < 5 and OPEN <= at.time() <= CLOSE


def is_expected_session(at: datetime | None = None) -> bool:
    """Whether data *should* be arriving now — the market open check plus
    holidays. Used for alerting, where a holiday must not raise a false alarm.
    """
    at = (at or now_ist()).astimezone(IST)
    return is_market_open(at) and not is_holiday(at.date())


#: Upstox tokens expire at this wall-clock time in IST, regardless of issue time.
TOKEN_EXPIRY = time(3, 30)


def next_token_expiry(issued: datetime | None = None) -> datetime:
    """The next 03:30 IST at or after `issued` — when an Upstox token dies.

    A token issued at 02:00 IST expires the SAME day at 03:30; one issued at
    any later hour expires 03:30 the following day.
    """
    issued = (issued or now_ist()).astimezone(IST)
    today_expiry = issued.replace(
        hour=TOKEN_EXPIRY.hour, minute=TOKEN_EXPIRY.minute, second=0, microsecond=0
    )
    if issued <= today_expiry:
        return today_expiry
    return today_expiry + timedelta(days=1)


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
