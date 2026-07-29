"""
Unit tests for the Pine function ports.

These are parity tests, not behaviour tests: each one pins a property the
TradingView built-in is known to have, so that a future "tidy-up" of
indicators.py that silently changes the maths fails here rather than in a
backtest nobody re-runs.
"""
import numpy as np
import pytest

from mutanabby.indicators import (
    atr,
    crossover,
    crossunder,
    nz,
    rma,
    rsi,
    sma,
    supertrend,
    true_range,
)


class TestNz:
    def test_replaces_nan(self):
        assert nz(np.nan) == 0.0
        assert nz(np.nan, 5.0) == 5.0

    def test_passes_through_real_values(self):
        assert nz(3.5) == 3.5
        assert nz(0.0, 9.0) == 0.0


class TestSma:
    def test_is_nan_until_length_bars_exist(self):
        out = sma(np.array([1.0, 2.0, 3.0, 4.0]), 3)
        assert np.isnan(out[0]) and np.isnan(out[1])
        assert out[2] == pytest.approx(2.0)
        assert out[3] == pytest.approx(3.0)

    def test_rejects_non_positive_length(self):
        with pytest.raises(ValueError):
            sma(np.array([1.0, 2.0]), 0)


class TestRma:
    def test_seeds_with_sma_then_applies_wilder_alpha(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        out = rma(values, 3)
        assert np.isnan(out[0]) and np.isnan(out[1])
        # Seed = mean(1,2,3) = 2.0
        assert out[2] == pytest.approx(2.0)
        # alpha = 1/3 -> 4/3 + 2*(2/3) = 2.6667
        assert out[3] == pytest.approx(2.0 + (4.0 - 2.0) / 3.0)
        assert out[4] == pytest.approx(out[3] + (5.0 - out[3]) / 3.0)

    def test_skips_leading_nan_before_seeding(self):
        # Mirrors ta.change(), whose first element is na.
        values = np.array([np.nan, 2.0, 4.0, 6.0])
        out = rma(values, 2)
        assert np.isnan(out[0]) and np.isnan(out[1])
        assert out[2] == pytest.approx(3.0)   # mean(2, 4)

    def test_returns_all_nan_when_series_shorter_than_length(self):
        assert np.all(np.isnan(rma(np.array([1.0, 2.0]), 5)))


class TestTrueRange:
    def test_first_bar_falls_back_to_high_minus_low(self):
        # ta.tr(true): no previous close exists, so bar 0 is high - low.
        high = np.array([10.0, 11.0])
        low = np.array([9.0, 10.5])
        close = np.array([9.5, 11.0])
        tr = true_range(high, low, close)
        assert tr[0] == pytest.approx(1.0)

    def test_uses_gap_against_previous_close(self):
        high = np.array([10.0, 20.0])
        low = np.array([9.0, 19.0])
        close = np.array([9.5, 19.5])
        tr = true_range(high, low, close)
        # |20 - 9.5| = 10.5 beats the 1.0 intrabar range.
        assert tr[1] == pytest.approx(10.5)

    def test_atr_is_rma_of_true_range(self):
        rng = np.random.default_rng(0)
        close = np.cumsum(rng.normal(0, 1, 60)) + 100
        high = close + 1.0
        low = close - 1.0
        assert np.allclose(
            atr(high, low, close, 14),
            rma(true_range(high, low, close), 14),
            equal_nan=True,
        )


class TestRsi:
    def test_monotonic_rise_reads_100(self):
        # Every change is positive -> down == 0 -> Pine's first branch.
        out = rsi(np.arange(1.0, 40.0), 14)
        assert out[-1] == pytest.approx(100.0)

    def test_monotonic_fall_reads_0(self):
        out = rsi(np.arange(40.0, 1.0, -1.0), 14)
        assert out[-1] == pytest.approx(0.0)

    def test_stays_within_bounds(self):
        rng = np.random.default_rng(7)
        series = np.cumsum(rng.normal(0, 1, 300)) + 100
        out = rsi(series, 14)
        valid = out[~np.isnan(out)]
        assert len(valid) > 0
        assert valid.min() >= 0.0 and valid.max() <= 100.0


class TestCrosses:
    def test_crossover_requires_a_strict_break_from_at_or_below(self):
        a = np.array([1.0, 1.0, 2.0, 3.0])
        b = np.array([2.0, 2.0, 1.0, 1.0])
        out = crossover(a, b)
        assert list(out) == [False, False, True, False]

    def test_crossunder_is_the_mirror(self):
        a = np.array([3.0, 3.0, 1.0, 0.5])
        b = np.array([2.0, 2.0, 2.0, 2.0])
        out = crossunder(a, b)
        assert list(out) == [False, False, True, False]

    def test_nan_never_produces_a_cross(self):
        a = np.array([np.nan, np.nan, 2.0])
        b = np.array([1.0, 1.0, 1.0])
        assert not crossover(a, b)[1]
        # Bar 2 has a valid pair but a[1] is nan, so the prior-bar test fails.
        assert not crossover(a, b)[2]


class TestSupertrend:
    @staticmethod
    def _series(n=200, seed=3):
        rng = np.random.default_rng(seed)
        close = np.cumsum(rng.normal(0, 1.0, n)) + 100.0
        high = close + rng.uniform(0.2, 1.0, n)
        low = close - rng.uniform(0.2, 1.0, n)
        return high, low, close

    def test_direction_is_only_ever_plus_or_minus_one(self):
        high, low, close = self._series()
        _, direction = supertrend(high, low, close, 4.0, 11)
        assert set(np.unique(direction)) <= {-1.0, 1.0}

    def test_warmup_bars_are_forced_to_downtrend(self):
        # Pine: `if na(atr[1]) -> direction := 1`. ATR(11) seeds at index 10,
        # so atr[i-1] is na for i = 0..10.
        high, low, close = self._series()
        _, direction = supertrend(high, low, close, 4.0, 11)
        assert np.all(direction[:11] == 1.0)

    def test_line_sits_below_price_in_uptrend_and_above_in_downtrend(self):
        high, low, close = self._series()
        st, direction = supertrend(high, low, close, 4.0, 11)
        settled = slice(20, None)
        up = direction[settled] == -1.0
        down = direction[settled] == 1.0
        assert np.all(st[settled][up] <= close[settled][up])
        assert np.all(st[settled][down] >= close[settled][down])

    def test_bands_ratchet_and_only_reset_on_a_flip(self):
        # The defining SuperTrend property: while direction holds, the line
        # never moves against the trade.
        high, low, close = self._series(seed=11)
        st, direction = supertrend(high, low, close, 4.0, 11)
        for i in range(21, len(st)):
            if direction[i] != direction[i - 1] or np.isnan(st[i - 1]):
                continue
            if direction[i] == -1.0:      # uptrend: line may only rise
                assert st[i] >= st[i - 1] - 1e-9
            else:                          # downtrend: line may only fall
                assert st[i] <= st[i - 1] + 1e-9

    def test_is_causal(self):
        # Truncating future bars must not change any past value — the property
        # that makes precomputing the whole series in strategy.py legitimate.
        high, low, close = self._series(n=300, seed=5)
        full, full_dir = supertrend(high, low, close, 4.0, 11)
        cut = 180
        part, part_dir = supertrend(high[:cut], low[:cut], close[:cut], 4.0, 11)
        assert np.allclose(full[:cut], part, equal_nan=True)
        assert np.allclose(full_dir[:cut], part_dir, equal_nan=True)

    def test_lower_sensitivity_flips_more_often(self):
        high, low, close = self._series(n=400, seed=9)
        _, tight = supertrend(high, low, close, 1.0, 11)
        _, loose = supertrend(high, low, close, 8.0, 11)
        flips_tight = int(np.sum(np.diff(tight) != 0))
        flips_loose = int(np.sum(np.diff(loose) != 0))
        assert flips_tight > flips_loose
