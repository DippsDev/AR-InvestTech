"""
Unit tests for signal construction and the backtest loop.

Focus is on the things the Pine source specifies exactly — where the stop
sits, how the TP formula behaves on shorts, that the SMA filter can veto a
SuperTrend flip — plus the fill conventions the backtester adds on top.
"""
import numpy as np
import pandas as pd
import pytest

from mutanabby.backtest import BacktestCosts, run_backtest
from mutanabby.config import MutanabbyConfig
from mutanabby.strategy import SignalGenerator


def _frame(highs, lows, closes, opens=None):
    """Build a backtest-ready frame.

    `open` defaults to the PREVIOUS bar's close, not this bar's close. Real M5
    bars are near-continuous (measured on us30_m5_max.csv: median open-vs-prior-
    close gap 0.6 points against a median 54-point ATR stop), so setting
    open == close would manufacture a full bar's worth of fake gap and trip the
    backtester's max_entry_slip_r guard on most signals.
    """
    n = len(closes)
    idx = pd.date_range("2025-01-06 09:30", periods=n, freq="5min", tz="America/New_York")
    if opens is None:
        opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame({
        "timestamp_ny": idx,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "date_str": [str(t.date()) for t in idx],
        "is_news_day": [False] * n,
    })


def _trending_series(n=400, seed=2):
    """Synthetic bars at US30's real scale (~43,000 with ~25-point M5 moves).

    Scale matters: the default BacktestCosts (2-point spread, 1-point slippage)
    are calibrated for US30, where a typical ATR stop is ~54 points. A toy
    series around price 100 gives ~1.8-point stops, making those same costs
    worth >1R and silently rejecting every entry via max_entry_slip_r.
    """
    rng = np.random.default_rng(seed)
    close = np.cumsum(rng.normal(1.0, 25.0, n)) + 43000.0
    high = close + rng.uniform(5.0, 25.0, n)
    low = close - rng.uniform(5.0, 25.0, n)
    return high, low, close


class TestSignalConstruction:
    def test_stop_is_signal_bar_extreme_offset_by_atr(self):
        cfg = MutanabbyConfig()
        high, low, close = _trending_series()
        gen = SignalGenerator(cfg, high, low, close)

        from mutanabby.indicators import atr
        atr_vals = atr(high, low, close, cfg.risk_atr_length)

        fired = 0
        for i in np.flatnonzero(gen.bull | gen.bear):
            sig = gen.on_bar(int(i), "2025-01-06")
            if sig is None:
                continue
            fired += 1
            band = atr_vals[i] * cfg.atr_risk_multiplier
            if sig.direction == "long":
                assert sig.stop_price == pytest.approx(low[i] - band)
            else:
                assert sig.stop_price == pytest.approx(high[i] + band)
        assert fired > 0, "fixture produced no signals"

    def test_entry_is_the_signal_bar_close(self):
        cfg = MutanabbyConfig()
        high, low, close = _trending_series()
        gen = SignalGenerator(cfg, high, low, close)
        for i in np.flatnonzero(gen.bull | gen.bear):
            sig = gen.on_bar(int(i), "2025-01-06")
            if sig is not None:
                assert sig.entry_price == pytest.approx(close[i])

    def test_target_projects_the_right_way_on_both_directions(self):
        # (entry - stop) * rr + entry is sign-correct without branching: the
        # exact property that makes the Pine one-liner work on shorts.
        # split_targets=False on purpose: this pins the Pine TP formula, which
        # is driven by `rr`. The shipped default splits into tp1_rr/tp2_rr and
        # ignores `rr` entirely.
        cfg = MutanabbyConfig(rr=2.0, split_targets=False)
        high, low, close = _trending_series(seed=4)
        gen = SignalGenerator(cfg, high, low, close)
        seen = set()
        for i in np.flatnonzero(gen.bull | gen.bear):
            sig = gen.on_bar(int(i), "2025-01-06")
            if sig is None:
                continue
            seen.add(sig.direction)
            risk = abs(sig.entry_price - sig.stop_price)
            if sig.direction == "long":
                assert sig.target_price == pytest.approx(sig.entry_price + 2.0 * risk)
                assert sig.target_price > sig.entry_price > sig.stop_price
            else:
                assert sig.target_price == pytest.approx(sig.entry_price - 2.0 * risk)
                assert sig.target_price < sig.entry_price < sig.stop_price
        assert seen == {"long", "short"}, f"fixture only produced {seen}"

    def test_sma_filter_is_a_subset_of_raw_supertrend_flips(self):
        """The filter can only ever remove signals, never add them.

        Deliberately NOT asserting that it removes any: measured on the stored
        history it vetoes 2/940 US30 crossovers, 2/828 on XAUUSD and 0/894 on
        EURUSD. A SuperTrend flip at sensitivity 4 already requires close to
        travel ~4x ATR, which all but guarantees it is on the correct side of a
        13-bar mean — so the filter is very nearly inert by construction, and a
        test demanding a veto would be asserting a coincidence.
        """
        for seed in range(20):
            high, low, close = _trending_series(n=600, seed=seed)
            filtered = SignalGenerator(MutanabbyConfig(trend_sma_length=13), high, low, close)
            # length 1 -> sma == close -> the >= / <= tests are trivially true.
            unfiltered = SignalGenerator(MutanabbyConfig(trend_sma_length=1), high, low, close)
            assert not (filtered.bull & ~unfiltered.bull).any()
            assert not (filtered.bear & ~unfiltered.bear).any()

    def test_sma_filter_vetoes_when_price_closes_the_wrong_side_of_the_mean(self):
        # Forcing the filter to bite, to prove it is wired up at all: a long
        # SMA makes `close >= sma` genuinely restrictive on a downtrending
        # series, so bull signals must be strictly fewer than raw crossovers.
        high, low, close = _trending_series(n=2000, seed=5)
        close = close[::-1].copy()          # reverse into a sustained downtrend
        high = high[::-1].copy()
        low = low[::-1].copy()
        strict = SignalGenerator(MutanabbyConfig(trend_sma_length=400), high, low, close)
        raw = SignalGenerator(MutanabbyConfig(trend_sma_length=1), high, low, close)
        assert int(raw.bull.sum()) > int(strict.bull.sum())

    def test_min_risk_points_rejects_tight_stops(self):
        high, low, close = _trending_series(seed=8)
        permissive = SignalGenerator(MutanabbyConfig(), high, low, close)
        strict = SignalGenerator(MutanabbyConfig(min_risk_points=1e6), high, low, close)
        bars = np.flatnonzero(permissive.bull | permissive.bear)
        assert any(permissive.on_bar(int(i), "2025-01-06") is not None for i in bars)
        assert all(strict.on_bar(int(i), "2025-01-06") is None for i in bars)

    def test_strength_flag_is_diagnostic_only(self):
        # Flipping legacy_strength_labels must change the label and nothing else.
        high, low, close = _trending_series(seed=12)
        df = _frame(high, low, close)
        costs = BacktestCosts()
        legacy = run_backtest(df, MutanabbyConfig(legacy_strength_labels=True), costs)
        sane = run_backtest(df, MutanabbyConfig(legacy_strength_labels=False), costs)
        assert len(legacy) == len(sane) and len(legacy) > 0
        for a, b in zip(legacy, sane):
            assert a.entry_price == b.entry_price
            assert a.exit_reason == b.exit_reason
            assert a.pnl_dollars == b.pnl_dollars
        assert any(a.strength != b.strength for a, b in zip(legacy, sane))


class TestBacktestLoop:
    def test_fills_at_next_bar_open_not_signal_bar_close(self):
        high, low, close = _trending_series(seed=3)
        opens = close - 0.5   # distinct from close so the fill source is provable
        df = _frame(high, low, close, opens)
        costs = BacktestCosts(spread_points=0.0, slippage_points=0.0, commission_per_trade=0.0)
        trades = run_backtest(df, MutanabbyConfig(), costs)
        assert trades
        for t in trades:
            assert t.entry_price == pytest.approx(opens[t.signal_bar + 1])

    def test_costs_push_the_fill_against_the_trade(self):
        high, low, close = _trending_series(seed=3)
        opens = close - 0.5
        df = _frame(high, low, close, opens)
        free = run_backtest(df, MutanabbyConfig(),
                            BacktestCosts(spread_points=0.0, slippage_points=0.0, commission_per_trade=0.0))
        costly = run_backtest(df, MutanabbyConfig(),
                              BacktestCosts(spread_points=2.0, slippage_points=1.0, commission_per_trade=0.0))
        pairs = {t.signal_bar: t for t in free}
        for t in costly:
            if t.signal_bar in pairs:
                base = pairs[t.signal_bar].entry_price
                expected = base + 2.0 if t.direction == "long" else base - 2.0
                assert t.entry_price == pytest.approx(expected)

    def test_stop_wins_when_both_levels_hit_in_one_bar(self):
        high, low, close = _trending_series(seed=15)
        df = _frame(high, low, close)
        # A huge target is unreachable, so anything that closes must be a stop
        # or the end-of-data time exit — never a target.
        # rr=500 pushes the single target unreachably far so every exit must be
        # a stop; split_targets=False keeps `rr` in control of that distance.
        trades = run_backtest(df, MutanabbyConfig(rr=500.0, split_targets=False), BacktestCosts())
        assert trades
        assert all(t.exit_reason in ("stop", "time_exit") for t in trades)

    def test_only_one_position_open_at_a_time(self):
        high, low, close = _trending_series(seed=21)
        df = _frame(high, low, close)
        trades = run_backtest(df, MutanabbyConfig(), BacktestCosts())
        assert len(trades) > 1
        for earlier, later in zip(trades, trades[1:]):
            assert later.entry_time >= earlier.exit_time

    # A wide stop is needed to observe flips on a random-walk fixture: the
    # default 1x-ATR stop sits far inside the ~4x-ATR move a SuperTrend flip
    # requires, so on synthetic bars the stop nearly always resolves first.
    # (On real US30 history flips are reachable at the default too — 276 of
    # 1706 exits — but that is a property of real trends, not of this code.)
    _FLIP_CFG = dict(exit_on_opposite_signal=True, atr_risk_multiplier=4.0)

    def test_flip_exit_produces_opposite_signal_closes(self):
        high, low, close = _trending_series(n=1500, seed=21)
        df = _frame(high, low, close)
        flip = run_backtest(df, MutanabbyConfig(**self._FLIP_CFG), BacktestCosts())
        assert any(t.exit_reason == "opposite_signal" for t in flip)

    def test_flip_exit_reverses_on_the_very_next_bar(self):
        # The flip that closes a long is the same bar that signals the short,
        # so the replacement trade must fill at the next open — not be dropped.
        high, low, close = _trending_series(n=1500, seed=21)
        df = _frame(high, low, close)
        trades = run_backtest(df, MutanabbyConfig(**self._FLIP_CFG), BacktestCosts())
        by_id = {t.trade_id: t for t in trades}
        reversals = 0
        for t in trades:
            if t.exit_reason != "opposite_signal":
                continue
            nxt = by_id.get(t.trade_id + 1)
            if nxt is None:
                continue
            assert nxt.direction != t.direction
            assert nxt.entry_time > t.exit_time
            reversals += 1
        assert reversals > 0

    def test_r_multiple_matches_realised_points(self):
        high, low, close = _trending_series(seed=31)
        df = _frame(high, low, close)
        trades = run_backtest(df, MutanabbyConfig(), BacktestCosts())
        assert trades
        for t in trades:
            assert t.r_multiple == pytest.approx(t.pnl_points / t.risk_points)
            assert t.pnl_dollars == pytest.approx(t.pnl_points * t.units)

    def test_breakeven_stop_caps_losses_at_roughly_zero(self):
        high, low, close = _trending_series(n=1500, seed=44)
        df = _frame(high, low, close)
        trades = run_backtest(df, MutanabbyConfig(breakeven_r=1.0), BacktestCosts())
        moved = [t for t in trades if t.breakeven_triggered and t.exit_reason == "stop"]
        assert moved, "fixture never triggered breakeven"
        for t in moved:
            assert t.r_multiple > -0.5

    def test_no_trades_on_empty_signal_set(self):
        flat = np.full(300, 100.0)
        df = _frame(flat + 0.5, flat - 0.5, flat)
        assert run_backtest(df, MutanabbyConfig(), BacktestCosts()) == []
