from datetime import datetime, timedelta

from app.market_hours import IST
from app.status import STALE_AFTER_INTERVALS, is_stale

INTERVAL = 300  # 5 minutes
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=IST)  # a Tuesday, mid-session


class TestIsStale:
    """Staleness is what catches a dead recorder, so the edges matter."""

    def test_recent_capture_is_not_stale(self):
        assert not is_stale(NOW - timedelta(seconds=60), True, INTERVAL, NOW)

    def test_one_missed_interval_is_tolerated(self):
        # A single hiccup should not raise an alarm.
        assert not is_stale(NOW - timedelta(seconds=INTERVAL + 1), True, INTERVAL, NOW)

    def test_beyond_threshold_is_stale(self):
        gap = INTERVAL * STALE_AFTER_INTERVALS + 1
        assert is_stale(NOW - timedelta(seconds=gap), True, INTERVAL, NOW)

    def test_no_capture_at_all_during_market_is_stale(self):
        assert is_stale(None, True, INTERVAL, NOW)

    def test_never_stale_when_market_closed(self):
        # Otherwise the banner would cry wolf every single evening.
        assert not is_stale(NOW - timedelta(days=3), False, INTERVAL, NOW)

    def test_no_capture_when_market_closed_is_not_stale(self):
        assert not is_stale(None, False, INTERVAL, NOW)
