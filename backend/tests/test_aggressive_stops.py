"""Tests for the aggressive-mode stop overlay.

The overlay must land on the *scaled* per-symbol buffer (after SB_TARGETS /
TL_TARGETS), never tighten a knob that is already looser, and never switch
Mutanabby onto breakeven/trail — those would silently change live behaviour.
"""
from dataclasses import replace

import pytest

from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS
from mutanabby.config import MutanabbyConfig
from silver_bullet.config import SilverBulletConfig
from src.aggressive_stops import (
    ATR_RISK_MULT,
    BREAKEVEN_R,
    EARLY_EXIT_R,
    STOP_BUFFER_MULT,
    TRAIL_R,
    apply_aggressive_stops,
)
from trendline.config import TrendlineConfig


class TestSilverBullet:
    def test_buffer_is_multiplied(self):
        cfg = SilverBulletConfig(stop_buffer_points=1.5)
        out = apply_aggressive_stops(cfg)
        assert out.stop_buffer_points == pytest.approx(1.5 * STOP_BUFFER_MULT)
        assert cfg.stop_buffer_points == 1.5  # original untouched

    def test_breakeven_and_trail_loosen(self):
        cfg = SilverBulletConfig()
        assert cfg.breakeven_r == 0.25
        assert cfg.trail_r == 0.1
        assert cfg.early_exit_r == 0.4
        out = apply_aggressive_stops(cfg)
        assert out.breakeven_r == BREAKEVEN_R
        assert out.trail_r == TRAIL_R
        assert out.early_exit_r == EARLY_EXIT_R

    def test_off_hours_management_loosens_too(self):
        cfg = SilverBulletConfig()
        out = apply_aggressive_stops(cfg)
        assert out.off_hours_breakeven_r == BREAKEVEN_R
        assert out.off_hours_trail_r == TRAIL_R
        assert out.off_hours_early_exit_r == EARLY_EXIT_R

    def test_lands_on_the_scaled_symbol_buffer(self):
        # bot.py applies this AFTER SB_TARGETS overrides. If it ran first,
        # the per-symbol buffer would clobber the 8× and aggressive mode
        # would still trade the tight live stops.
        for symbol, overrides in SB_TARGETS.items():
            cfg = replace(SilverBulletConfig(), symbol=symbol, **overrides)
            out = apply_aggressive_stops(cfg)
            assert out.stop_buffer_points == pytest.approx(
                overrides["stop_buffer_points"] * STOP_BUFFER_MULT
            ), symbol


class TestTrendline:
    def test_buffer_is_multiplied(self):
        cfg = TrendlineConfig(stop_buffer_points=5.0)
        out = apply_aggressive_stops(cfg)
        assert out.stop_buffer_points == pytest.approx(5.0 * STOP_BUFFER_MULT)

    def test_does_not_tighten_an_already_looser_breakeven(self):
        # TL ships at 1.0R BE / 0.5R trail — already at or past the overlay.
        cfg = TrendlineConfig()
        out = apply_aggressive_stops(cfg)
        assert out.breakeven_r == pytest.approx(cfg.breakeven_r)
        assert out.trail_r == pytest.approx(max(cfg.trail_r, TRAIL_R))

    def test_lands_on_the_scaled_symbol_buffer(self):
        for symbol, overrides in TL_TARGETS.items():
            cfg = replace(TrendlineConfig(), symbol=symbol, **overrides)
            out = apply_aggressive_stops(cfg)
            assert out.stop_buffer_points == pytest.approx(
                overrides["stop_buffer_points"] * STOP_BUFFER_MULT
            ), symbol


class TestMutanabby:
    def test_atr_stop_doubles_and_management_stays_off(self):
        cfg = MutanabbyConfig()
        out = apply_aggressive_stops(cfg)
        assert out.atr_risk_multiplier == pytest.approx(
            cfg.atr_risk_multiplier * ATR_RISK_MULT
        )
        assert out.breakeven_r == 0.0
        assert out.trail_r == 0.0

    def test_targets_do_not_reintroduce_management(self):
        for symbol, overrides in MB_TARGETS.items():
            cfg = replace(MutanabbyConfig(), symbol=symbol, **overrides)
            out = apply_aggressive_stops(cfg)
            assert out.breakeven_r == 0.0, symbol
            assert out.trail_r == 0.0, symbol
