"""
Unit tests for trendline construction, invalidation, and touch detection.

Tolerance values used here are illustrative round numbers matched to each
fixture's own price scale, not the production TrendlineConfig defaults
(which assume MT5 "point" units) — build_support_line/build_resistance_line
take these as plain parameters, so any consistent scale works.
"""
import numpy as np
import pytest

from trendline.indicators import (
    build_resistance_line,
    build_support_line,
    check_breach,
    check_touch,
    is_same_line,
    value_at,
)


class TestLineConstruction:
    def test_builds_support_line_from_two_confirmed_swing_lows(self):
        # Swing lows at bar 2 (1.05) and bar 8 (1.07), lookback=2, gentle
        # ascending slope. Bars in between stay well above the line.
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.10, 1.09, 1.08, 1.09, 1.07, 1.09, 1.10])
        highs = lows + 0.02
        line = build_support_line(
            lows, highs, current_bar=10, swing_lookback=2,
            avg_range_lookback=20, steepness_max_ratio=1.0,
            obstruction_tolerance_points=0.001,
        )
        assert line is not None
        assert line.kind == "support"
        assert (line.anchor1_bar, line.anchor1_price) == (2, 1.05)
        assert (line.anchor2_bar, line.anchor2_price) == (8, 1.07)
        assert value_at(line, 8) == pytest.approx(1.07)
        assert value_at(line, 2) == pytest.approx(1.05)

    def test_builds_resistance_line_from_two_confirmed_swing_highs(self):
        # Symmetric: swing highs at bar 2 (1.10) and bar 8 (1.08), descending.
        highs = np.array([1.05, 1.06, 1.10, 1.06, 1.05, 1.06, 1.07, 1.06, 1.08, 1.06, 1.05])
        lows  = highs - 0.02
        line = build_resistance_line(
            lows, highs, current_bar=10, swing_lookback=2,
            avg_range_lookback=20, steepness_max_ratio=1.0,
            obstruction_tolerance_points=0.001,
        )
        assert line is not None
        assert line.kind == "resistance"
        assert (line.anchor1_bar, line.anchor1_price) == (2, 1.10)
        assert (line.anchor2_bar, line.anchor2_price) == (8, 1.08)

    def test_rejects_line_drawn_through_an_obstruction(self):
        # Same anchors as the successful case (bar 2 = 1.05, bar 8 = 1.07,
        # lookback=1 so bars 4-5 sit outside both anchors' own confirmation
        # windows and can't become swing lows themselves — a tied dip at
        # bars 4-5 fails the strict fractal check on both, per is_swing_low).
        # Bar 4's low (1.03) undercuts the interpolated line (~1.057) by far
        # more than the tolerance -> rejected as "drawn through an obstruction".
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.03, 1.03, 1.06, 1.09, 1.07, 1.09, 1.10])
        highs = lows + 0.02
        line = build_support_line(
            lows, highs, current_bar=10, swing_lookback=1,
            avg_range_lookback=20, steepness_max_ratio=1.0,
            obstruction_tolerance_points=0.001,
        )
        assert line is None

    def test_rejects_line_that_is_too_steep(self):
        # Swing lows at bar 1 (1.00) and bar 3 (1.04), lookback=1.
        # slope = 0.02/bar; avg bar range ~0.01 -> max allowed slope = 0.01.
        lows  = np.array([1.05, 1.00, 1.05, 1.04, 1.05, 1.03])
        highs = lows + 0.01
        line = build_support_line(
            lows, highs, current_bar=5, swing_lookback=1,
            avg_range_lookback=20, steepness_max_ratio=1.0,
            obstruction_tolerance_points=0.001,
        )
        assert line is None

    def test_needs_at_least_two_confirmed_swings(self):
        # Only one confirmed swing low exists in this short array.
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.10])
        highs = lows + 0.02
        line = build_support_line(
            lows, highs, current_bar=4, swing_lookback=2,
            avg_range_lookback=20, steepness_max_ratio=1.0,
            obstruction_tolerance_points=0.001,
        )
        assert line is None


class TestIsSameLine:
    def test_same_anchors_is_same_line(self):
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.10, 1.09, 1.08, 1.09, 1.07, 1.09, 1.10])
        highs = lows + 0.02
        line_a = build_support_line(lows, highs, 10, 2, 20, 1.0, 0.001)
        line_b = build_support_line(lows, highs, 10, 2, 20, 1.0, 0.001)
        assert is_same_line(line_a, line_b) is True

    def test_none_is_never_the_same_line(self):
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.10, 1.09, 1.08, 1.09, 1.07, 1.09, 1.10])
        highs = lows + 0.02
        line = build_support_line(lows, highs, 10, 2, 20, 1.0, 0.001)
        assert is_same_line(line, None) is False
        assert is_same_line(None, line) is False


class TestBreachAndTouch:
    def _sample_support_line(self):
        lows  = np.array([1.10, 1.09, 1.05, 1.09, 1.10, 1.09, 1.08, 1.09, 1.07, 1.09, 1.10])
        highs = lows + 0.02
        return build_support_line(lows, highs, 10, 2, 20, 1.0, 0.001)

    def test_light_breach_does_not_count_as_broken(self):
        line = self._sample_support_line()
        # Line value at bar 10 is 1.07 + slope*(10-8). A close just under the
        # line, within tolerance, should NOT count as a breach.
        val_at_10 = value_at(line, 10)
        close = val_at_10 - 0.0005   # small dip, well inside tolerance=0.01
        assert check_breach(line, 10, close, tolerance=0.01) is False

    def test_hard_breach_counts_as_broken(self):
        line = self._sample_support_line()
        val_at_10 = value_at(line, 10)
        close = val_at_10 - 0.02   # well beyond tolerance=0.01
        assert check_breach(line, 10, close, tolerance=0.01) is True

    def test_touch_within_tolerance(self):
        line = self._sample_support_line()
        val_at_10 = value_at(line, 10)
        low = val_at_10 - 0.0005
        assert check_touch(line, 10, high=low + 0.01, low=low, tolerance=0.01) is True

    def test_no_touch_when_far_above_line(self):
        line = self._sample_support_line()
        val_at_10 = value_at(line, 10)
        low = val_at_10 + 0.5   # nowhere near the line
        assert check_touch(line, 10, high=low + 0.01, low=low, tolerance=0.01) is False

    def test_no_touch_when_far_below_line(self):
        # A bar whose low crashed straight through and well past the line
        # (a breakout, not a touch) must not be flagged as a touch.
        line = self._sample_support_line()
        val_at_10 = value_at(line, 10)
        low = val_at_10 - 0.5
        assert check_touch(line, 10, high=low + 0.01, low=low, tolerance=0.01) is False
