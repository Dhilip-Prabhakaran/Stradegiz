from app.analytics import (
    LONG_BUILD_UP,
    LONG_UNWINDING,
    NEUTRAL,
    SHORT_BUILD_UP,
    SHORT_COVERING,
    interpret_oi,
)


class TestInterpretOi:
    """The four-quadrant OI/price reading these screens are built around."""

    def test_oi_up_price_up_is_long_build_up(self):
        assert interpret_oi(50_000, 2.5) == LONG_BUILD_UP

    def test_oi_up_price_down_is_short_build_up(self):
        assert interpret_oi(50_000, -2.5) == SHORT_BUILD_UP

    def test_oi_down_price_up_is_short_covering(self):
        assert interpret_oi(-50_000, 2.5) == SHORT_COVERING

    def test_oi_down_price_down_is_long_unwinding(self):
        assert interpret_oi(-50_000, -2.5) == LONG_UNWINDING

    def test_flat_oi_is_neutral(self):
        assert interpret_oi(0, 2.5) == NEUTRAL

    def test_flat_price_is_neutral(self):
        assert interpret_oi(50_000, 0) == NEUTRAL

    def test_unknown_change_is_neutral(self):
        # First bucket of a day has no predecessor to diff against.
        assert interpret_oi(None, 2.5) == NEUTRAL
        assert interpret_oi(50_000, None) == NEUTRAL
