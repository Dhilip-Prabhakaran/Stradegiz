from datetime import datetime

from app.market_hours import IST, is_market_open, next_tick

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
