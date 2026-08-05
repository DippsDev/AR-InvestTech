"""Tests for the two-target (TP1/TP2) position split.

The split touches all three strategies, so the risks worth pinning are the ones
that would be silent in live trading: legs that the broker would reject, targets
that end up in the wrong order, a trade count that double-counts one setup, and
P/L that forgets a banked leg.
"""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.split_target import r_target, split_lots, validate_split

from silver_bullet.config import SilverBulletConfig
from trendline.backtest import BacktestCosts as TLCosts, Trade as TLTrade, _finalise_trade
from trendline.config import TrendlineConfig
from mutanabby.config import MutanabbyConfig


class TestRTarget:
    def test_projects_away_from_stop_on_both_directions(self):
        # risk is always positive; direction alone carries the sign
        assert r_target("long", 100.0, 10.0, 3.0) == pytest.approx(130.0)
        assert r_target("short", 100.0, 10.0, 3.0) == pytest.approx(70.0)

    def test_tp2_sits_beyond_tp1_on_a_short(self):
        tp1 = r_target("short", 100.0, 10.0, 3.0)
        tp2 = r_target("short", 100.0, 10.0, 4.0)
        assert tp2 < tp1 < 100.0


class TestSplitLots:
    def test_splits_evenly_on_the_volume_grid(self):
        assert split_lots(1.00, 0.5, volume_min=0.01, volume_step=0.01) == (0.5, 0.5)

    def test_respects_a_non_half_fraction(self):
        leg1, leg2 = split_lots(1.00, 0.75, volume_min=0.01, volume_step=0.01)
        assert (leg1, leg2) == (0.75, 0.25)

    def test_legs_always_sum_to_the_original_size(self):
        # The rounding must not create or destroy exposure — leg2 is the
        # remainder, never independently rounded.
        for lots in (0.03, 0.07, 0.15, 1.23):
            leg1, leg2 = split_lots(lots, 0.5, 0.01, 0.01)
            assert leg1 + leg2 == pytest.approx(lots)

    def test_refuses_to_split_the_minimum_lot(self):
        # The live case on a small account: _compute_lots already floored at
        # volume_min, so half of it does not exist. Must be None, not a rounded
        # -up leg that would double the intended risk.
        assert split_lots(0.01, 0.5, volume_min=0.01, volume_step=0.01) is None

    def test_refuses_when_only_one_leg_would_be_too_small(self):
        # 0.02 at 90/10 gives a 0.002 second leg -> rounds to 0.0, below minimum
        assert split_lots(0.02, 0.9, volume_min=0.01, volume_step=0.01) is None

    def test_handles_a_coarse_volume_step(self):
        assert split_lots(2.0, 0.5, volume_min=0.5, volume_step=0.5) == (1.0, 1.0)
        assert split_lots(1.0, 0.5, volume_min=1.0, volume_step=0.5) is None


class TestValidateSplit:
    def test_rejects_tp2_at_or_below_tp1(self):
        # Equal targets would fill together: a no-op split paying two lots of
        # commission. Nearer TP2 would invert the legs outright.
        with pytest.raises(ValueError, match="strictly greater"):
            validate_split(3.0, 3.0, 0.5)
        with pytest.raises(ValueError, match="strictly greater"):
            validate_split(4.0, 3.0, 0.5)

    @pytest.mark.parametrize("fraction", [0.0, 1.0, -0.5, 1.5])
    def test_rejects_degenerate_fractions(self, fraction):
        with pytest.raises(ValueError, match="tp1_fraction"):
            validate_split(3.0, 4.0, fraction)

    def test_accepts_the_shipped_defaults_of_all_three_strategies(self):
        for cfg in (SilverBulletConfig(), TrendlineConfig(), MutanabbyConfig()):
            validate_split(cfg.tp1_rr, cfg.tp2_rr, cfg.tp1_fraction)

    def test_generators_reject_a_bad_split_at_construction(self):
        from trendline.strategy import SignalGenerator
        with pytest.raises(ValueError):
            SignalGenerator(replace(TrendlineConfig(), tp1_rr=4.0, tp2_rr=3.0))


class TestSplitPnl:
    """_finalise_trade's leg weighting (trendline's copy; the other two are
    line-for-line identical)."""

    def _trade(self, **kw):
        base = dict(
            trade_id=1, direction="long", date="2026-01-01",
            entry_time=pd.Timestamp("2026-01-01"), entry_price=100.0,
            stop_price=90.0, target_price=130.0, target_price_2=140.0,
            tp1_fraction=0.5, risk_points=10.0, units=10.0,
        )
        base.update(kw)
        return TLTrade(**base)

    def _costs(self):
        return TLCosts(commission_per_trade=0.0, point_value=1.0)

    def test_unsplit_trade_books_the_whole_move(self):
        t = self._trade(target_price_2=None, tp1_fraction=1.0, exit_price=130.0)
        _finalise_trade(t, self._costs())
        assert t.r_multiple == pytest.approx(3.0)

    def test_both_legs_filled_averages_the_two_targets(self):
        # 50% at 3R + 50% at 4R = 3.5R
        t = self._trade(tp1_hit=True, tp1_exit_price=130.0, exit_price=140.0)
        _finalise_trade(t, self._costs())
        assert t.r_multiple == pytest.approx(3.5)
        assert t.pnl_dollars == pytest.approx(350.0)

    def test_banked_leg_survives_the_runner_being_stopped_out(self):
        # TP1 at +3R, runner stopped at breakeven -> 0.5*3 + 0.5*0 = 1.5R.
        # Losing the banked leg here is the failure mode this pins.
        t = self._trade(tp1_hit=True, tp1_exit_price=130.0, exit_price=100.0)
        _finalise_trade(t, self._costs())
        assert t.r_multiple == pytest.approx(1.5)

    def test_shorts_weight_the_same_way(self):
        t = self._trade(direction="short", entry_price=100.0, stop_price=110.0,
                        target_price=70.0, target_price_2=60.0,
                        tp1_hit=True, tp1_exit_price=70.0, exit_price=60.0)
        _finalise_trade(t, self._costs())
        assert t.r_multiple == pytest.approx(3.5)

    def test_commission_is_charged_once_per_opened_leg(self):
        # Flat $5/round trip, 10 units. Unsplit: 5/10 = 0.5 points off.
        # Split: each leg pays the full $5 over its own half -> 1.0 point off.
        unsplit = self._trade(target_price_2=None, tp1_fraction=1.0, exit_price=130.0)
        _finalise_trade(unsplit, TLCosts(commission_per_trade=5.0, point_value=1.0))
        assert unsplit.pnl_points == pytest.approx(30.0 - 0.5)

        split = self._trade(tp1_hit=True, tp1_exit_price=130.0, exit_price=140.0)
        _finalise_trade(split, TLCosts(commission_per_trade=5.0, point_value=1.0))
        assert split.pnl_points == pytest.approx(35.0 - 1.0)


class TestSplitDoesNotDoubleCountTrades:
    def test_one_setup_stays_one_trade_row(self):
        """A split setup is one decision and must produce exactly one Trade row.

        If the legs were booked separately every frequency and win-rate figure
        would silently double. Note the split legitimately yields *fewer* rows
        than the single-target run: a runner held for TP2 stays open longer, and
        the backtester takes one trade at a time, so the extra holding time
        blocks later setups. That is a real effect of the split, not
        miscounting — hence the assertion is "never more", plus a uniqueness
        check that catches genuine double-booking.
        """
        from trendline.backtest import run_backtest
        from trendline.data import prepare_from_m5

        df = prepare_from_m5("data/de30m_m5_180d.csv")
        cfg = replace(
            TrendlineConfig(), touch_tolerance_points=6.722892,
            obstruction_tolerance_points=6.722892, breach_tolerance_points=3.734940,
            stop_buffer_points=3.734940, min_risk_points=11.204819,
            breakeven_r=0.0, trail_r=0.0,
        )
        costs = TLCosts(spread_points=1.4939759, slippage_points=0.74698795)

        split = run_backtest(df, cfg, costs)
        single = run_backtest(df, replace(cfg, split_targets=False), costs)

        assert len(split) <= len(single), (
            "splitting produced more trade rows than the single-target run — "
            "the legs are being counted separately"
        )
        entry_times = [t.entry_time for t in split]
        assert len(entry_times) == len(set(entry_times)), (
            "two trade rows share an entry time — one setup was booked twice"
        )
        # And the split actually engaged, so the checks above are meaningful.
        assert any(t.tp1_hit for t in split)
        assert all(t.target_price_2 is None for t in single)
