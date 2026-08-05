"""Tests for `_idle_between_bars`, the gate that lets an idle adapter skip a
cycle instead of refetching bars it has already scanned.

The gate is the one change in this pass that alters *when* an adapter does
work, so the contract worth pinning is precisely when it declines to skip:
never while a position or pending order is live (breakeven, trailing and
time-exit must keep their 5-second cadence), never when a new bar has closed,
and never when the previous cycle failed to fetch bars at all.
"""
from types import SimpleNamespace

import pytest

from mutanabby.config import MutanabbyConfig
from mutanabby.live_adapter import MutanabbyLiveAdapter
from silver_bullet.config import SilverBulletConfig
from silver_bullet.live_adapter import SilverBulletLiveAdapter
from trendline.config import TrendlineConfig
from trendline.live_adapter import TrendlineLiveAdapter


def _sb():
    return SilverBulletLiveAdapter(SilverBulletConfig(), symbol="DE30m")


def _tl():
    return TrendlineLiveAdapter(TrendlineConfig(), symbol="DE30m")


def _mb():
    return MutanabbyLiveAdapter(MutanabbyConfig(), symbol="US30m")


ALL_ADAPTERS = [pytest.param(_sb, id="SB"), pytest.param(_tl, id="TL"), pytest.param(_mb, id="MB")]


class TestBarPeriods:
    def test_periods_match_each_strategy_timeframe(self):
        # A wrong period here would either skip a bar's worth of signals (too
        # long) or defeat the optimisation entirely (too short).
        assert SilverBulletLiveAdapter._BAR_PERIOD_SEC == 300    # M5
        assert TrendlineLiveAdapter._BAR_PERIOD_SEC == 3600      # H1
        assert MutanabbyLiveAdapter._BAR_PERIOD_SEC == 3600      # H1


@pytest.mark.parametrize("make", ALL_ADAPTERS)
class TestGate:
    def test_first_call_never_skips(self, make):
        # A freshly started adapter has scanned nothing, so it must run a full
        # cycle to warm its generator state.
        assert make()._idle_between_bars() is False

    def test_skips_once_the_current_bar_has_been_scanned(self, make):
        adapter = make()
        adapter._mark_bar_scanned()
        assert adapter._idle_between_bars() is True

    def test_skips_stay_stable_across_many_ticks_in_one_bar(self, make):
        adapter = make()
        adapter._mark_bar_scanned()
        assert all(adapter._idle_between_bars() for _ in range(20))

    def test_a_new_bar_reopens_the_cycle(self, make):
        adapter = make()
        adapter._mark_bar_scanned()
        assert adapter._idle_between_bars() is True

        # Rewind the recorded boundary by one bar, as the clock crossing into
        # a new bar period would.
        adapter._last_bar_slot -= 1
        assert adapter._idle_between_bars() is False

    def test_an_open_position_always_forces_a_full_cycle(self, make):
        adapter = make()
        adapter._mark_bar_scanned()
        assert adapter._idle_between_bars() is True

        adapter._open[123] = SimpleNamespace(signal=None, fill_price=1.0)
        assert adapter._idle_between_bars() is False

    def test_gate_is_pure(self, make):
        # The boundary is consumed by _mark_bar_scanned after a successful
        # fetch, never by the gate itself — otherwise a failed fetch would
        # silently burn the bar it never scanned.
        adapter = make()
        for _ in range(5):
            adapter._idle_between_bars()
        assert adapter._last_bar_slot is None

    def test_a_failed_fetch_leaves_the_bar_unscanned(self, make):
        # Cycle 1: gate opens, fetch fails, _mark_bar_scanned is never reached.
        adapter = make()
        assert adapter._idle_between_bars() is False
        # Cycle 2, five seconds later: must retry rather than wait out the bar.
        assert adapter._idle_between_bars() is False


class TestPendingOrdersHoldSilverBulletOpen:
    def test_pending_order_forces_a_full_cycle(self):
        # SB is the only strategy using pending limit orders — fill detection
        # and window-end cancellation would otherwise stall for up to a bar.
        adapter = _sb()
        adapter._mark_bar_scanned()
        assert adapter._idle_between_bars() is True

        adapter._pending[456] = SimpleNamespace(signal=None, is_off_hours=False)
        assert adapter._idle_between_bars() is False
