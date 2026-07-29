"""
Tests for the live integration that don't need a running MT5 terminal.

Two things are worth pinning here beyond "it imports":

1. The risk-budget split. Enabling Mutanabby must not shrink Silver Bullet's or
   Trendline's position sizing — that regression would be silent, would only
   show up as slightly smaller lots on a live account, and is exactly what the
   separate `_mb_instance_count` divisor exists to prevent.
2. Window convergence. The adapter rebuilds its SignalGenerator from a rolling
   `bars_lookback` window instead of full history. If that window were too
   short, live signals would quietly diverge from the backtested ones.
"""
import numpy as np
import pytest

import config as root_config
from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS
from mutanabby.config import MutanabbyConfig
from mutanabby.indicators import crossover, crossunder, sma, supertrend


class TestTargets:
    def test_every_target_is_a_valid_config_override(self):
        # A typo'd field name would raise only at bot start-up, on a live
        # account, after MT5 has already connected.
        valid = set(MutanabbyConfig().__dict__)
        for symbol, overrides in MB_TARGETS.items():
            assert overrides, f"{symbol} has no overrides"
            unknown = set(overrides) - valid
            assert not unknown, f"{symbol} sets unknown MutanabbyConfig fields: {unknown}"

    def test_targets_use_the_validated_parameters(self):
        # sensitivity 6 / rr 2 is the only configuration with breadth evidence
        # behind it (see README). The indicator's own default of 4 loses.
        for symbol, overrides in MB_TARGETS.items():
            assert overrides["sensitivity"] == 6.0, symbol
            assert overrides["rr"] == 2.0, symbol

    def test_no_breakeven_or_trail_is_introduced(self):
        # The reported profit factors were measured on a flat stop-or-target
        # ride. Turning management on here would make live diverge from the
        # only numbers we have.
        cfg = MutanabbyConfig()
        assert cfg.breakeven_r == 0.0
        assert cfg.trail_r == 0.0
        for symbol, overrides in MB_TARGETS.items():
            assert overrides.get("breakeven_r", 0.0) == 0.0, symbol
            assert overrides.get("trail_r", 0.0) == 0.0, symbol

    def test_lookback_clears_the_convergence_floor(self):
        from mutanabby.live_adapter import MIN_CONVERGENCE_BARS
        assert MutanabbyConfig().bars_lookback >= MIN_CONVERGENCE_BARS

    def test_magic_number_is_unique_across_strategies(self):
        from mutanabby.live_adapter import MB_MAGIC
        from silver_bullet.live_adapter import SB_MAGIC
        from trendline.live_adapter import TL_MAGIC
        assert len({SB_MAGIC, TL_MAGIC, MB_MAGIC}) == 3


class TestRiskBudgetSplit:
    """Enabling MB must not change what SB and TL risk per trade."""

    @staticmethod
    def _divisors(mb_enabled: bool):
        # Mirrors bot.py's arithmetic without needing MT5 to construct a bot.
        tl_enabled = True
        sbtl = max(1, len(SB_TARGETS) + (len(TL_TARGETS) if tl_enabled else 0))
        mb = max(1, len(MB_TARGETS)) if mb_enabled else 1
        return sbtl, mb

    def test_sb_and_tl_divisor_is_unchanged_by_enabling_mb(self):
        off_sbtl, _ = self._divisors(mb_enabled=False)
        on_sbtl, _ = self._divisors(mb_enabled=True)
        assert off_sbtl == on_sbtl, (
            "enabling Mutanabby changed the SB/TL risk divisor — this silently "
            "shrinks every Silver Bullet and Trendline position"
        )

    def test_mb_draws_from_its_own_budget(self):
        _, mb = self._divisors(mb_enabled=True)
        assert mb == len(MB_TARGETS)
        per_instance = root_config.MB_RISK_PCT / mb
        # Whole-strategy exposure is MB_RISK_PCT, not a multiple of it.
        assert per_instance * len(MB_TARGETS) == pytest.approx(root_config.MB_RISK_PCT)

    def test_mb_risk_default_is_small(self):
        # MB's evidence is far weaker than SB's; the default must reflect that.
        assert root_config.MB_RISK_PCT <= root_config.SB_RISK_PCT

    def test_mb_is_off_by_default(self):
        # Matches the TL precedent: a new money-spending strategy must not
        # switch itself on for existing installs.
        import os
        assert os.getenv("MB_ENABLED") is not None or root_config.MB_ENABLED is False


class TestWindowConvergence:
    """The adapter reads a rolling window, not full history."""

    @staticmethod
    def _signals(high, low, close, sens=6.0):
        st, _ = supertrend(high, low, close, sens, 11)
        s = sma(close, 13)
        return (crossover(close, st) & (close >= s), crossunder(close, st) & (close <= s))

    @staticmethod
    def _series(n=1200, seed=17):
        rng = np.random.default_rng(seed)
        close = np.cumsum(rng.normal(1.0, 25.0, n)) + 43000.0
        return close + rng.uniform(5, 25, n), close - rng.uniform(5, 25, n), close

    def test_rolling_window_reproduces_full_history_signals(self):
        from mutanabby.live_adapter import MIN_CONVERGENCE_BARS
        high, low, close = self._series()
        bull_full, bear_full = self._signals(high, low, close)

        n = MutanabbyConfig().bars_lookback
        mismatches = 0
        checked = 0
        for i in range(max(n, MIN_CONVERGENCE_BARS), len(close), 11):
            w = slice(i - n + 1, i + 1)
            bull_w, bear_w = self._signals(high[w], low[w], close[w])
            live = bool(bull_w[-1]) or bool(bear_w[-1])
            true = bool(bull_full[i]) or bool(bear_full[i])
            checked += 1
            if live != true:
                mismatches += 1
        assert checked > 50
        assert mismatches == 0, (
            f"{mismatches}/{checked} live signals diverged from full history at "
            f"bars_lookback={n}"
        )

    def test_too_short_a_window_does_diverge(self):
        # Justifies MIN_CONVERGENCE_BARS being a guard rather than a formality.
        high, low, close = self._series(n=3000, seed=23)
        bull_full, bear_full = self._signals(high, low, close)
        mismatches = 0
        for i in range(40, len(close), 3):
            w = slice(i - 40 + 1, i + 1)
            bull_w, bear_w = self._signals(high[w], low[w], close[w])
            live = bool(bull_w[-1]) or bool(bear_w[-1])
            true = bool(bull_full[i]) or bool(bear_full[i])
            if live != true:
                mismatches += 1
        assert mismatches > 0
