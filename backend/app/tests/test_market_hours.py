from datetime import datetime

from app.market_hours import (
    IST,
    is_expected_session,
    is_holiday,
    is_market_open,
    is_trading_day,
    next_tick,
    next_token_expiry,
)

# 2026-07-21 is a Tuesday; 2026-07-25 a Saturday.
TUE = (2026, 7, 21)
SAT = (2026, 7, 25)


def ist(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=IST)


class TestIsMarketOpen:
    def test_closed_before_open(self):
        assert not is_market_open(ist(*TUE, 9, 14, 59))

    def test_open_at_bell(self):
        assert is_market_open(ist(*TUE, 9, 15))

    def test_open_midsession(self):
        assert is_market_open(ist(*TUE, 12, 3))

    def test_open_at_close_bell(self):
        assert is_market_open(ist(*TUE, 15, 30))

    def test_closed_after_close(self):
        assert not is_market_open(ist(*TUE, 15, 30, 1))

    def test_closed_on_weekend(self):
        assert not is_market_open(ist(*SAT, 12, 0))


class TestNextTick:
    def test_aligns_to_five_minute_boundary(self):
        assert next_tick(300, ist(*TUE, 12, 3, 27)) == ist(*TUE, 12, 5)

    def test_advances_when_already_on_boundary(self):
        # Must move forward, never return the current instant, or the loop
        # would busy-spin capturing the same timestamp repeatedly.
        assert next_tick(300, ist(*TUE, 12, 5)) == ist(*TUE, 12, 10)

    def test_one_minute_interval(self):
        assert next_tick(60, ist(*TUE, 12, 3, 27)) == ist(*TUE, 12, 4)

    def test_rolls_over_the_hour(self):
        assert next_tick(300, ist(*TUE, 12, 58, 1)) == ist(*TUE, 13, 0)


class TestHolidays:
    """The recorder must never be silenced by an advisory holiday list.

    Polling through a holiday costs a few wasted requests. Wrongly skipping a
    real session loses intraday history permanently, so the two mistakes are
    not equally bad and the code deliberately errs towards capturing.
    """

    # 2026-01-26 (Republic Day) is a Monday holiday.
    HOLIDAY = (2026, 1, 26)

    def test_date_is_recognised_as_a_holiday(self):
        assert is_holiday(ist(*self.HOLIDAY, 12, 0).date())

    def test_not_an_expected_trading_day(self):
        assert not is_trading_day(ist(*self.HOLIDAY, 12, 0).date())

    def test_recorder_still_captures_on_a_holiday(self):
        # The safety property: a wrong list entry must not stop recording.
        assert is_market_open(ist(*self.HOLIDAY, 12, 0))

    def test_no_session_expected_on_a_holiday(self):
        # ...but nothing is expected to arrive, so alerts stay quiet.
        assert not is_expected_session(ist(*self.HOLIDAY, 12, 0))

    def test_normal_trading_day_expects_a_session(self):
        assert is_expected_session(ist(*TUE, 12, 0))

    def test_holiday_outside_hours_expects_nothing(self):
        assert not is_expected_session(ist(*self.HOLIDAY, 20, 0))


class TestNextTokenExpiry:
    """Upstox tokens die at 03:30 IST regardless of when issued."""

    def test_evening_token_expires_next_morning(self):
        # Issued 20:00 Tue -> expires 03:30 Wed.
        assert next_token_expiry(ist(*TUE, 20, 0)) == ist(2026, 7, 22, 3, 30)

    def test_early_morning_token_expires_same_day(self):
        # Issued 02:30 Tue -> expires 03:30 Tue (same day).
        assert next_token_expiry(ist(*TUE, 2, 30)) == ist(*TUE, 3, 30)

    def test_token_issued_after_expiry_hour_rolls_to_next_day(self):
        # Issued 09:15 Tue -> expires 03:30 Wed.
        assert next_token_expiry(ist(*TUE, 9, 15)) == ist(2026, 7, 22, 3, 30)

    def test_exactly_at_expiry_boundary_is_same_day(self):
        assert next_token_expiry(ist(*TUE, 3, 30)) == ist(*TUE, 3, 30)
