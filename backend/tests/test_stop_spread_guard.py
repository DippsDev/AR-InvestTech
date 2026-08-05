"""Tests for `_stop_inside_spread`, the execution guard that refuses entries
whose stop cannot survive the spread.

The case that motivated it, taken from a live EURUSDm scan: a 4-point stop on
a symbol quoting an 8-point spread. A long fills at ask and is stopped when
bid reaches the SL, so that trade is already beyond its stop the moment it
opens — and sizing divides risk by the same 4 points, so it asks for the
largest position of the session on the way to a certain loss.

`min_risk_points` cannot catch it. That floor is a fixed price distance from
each symbol's historical volatility (EURUSDm: 0.0000562), and the adaptive
trade-floor booster halves it again; the spread is live and moves with the
session. Hence a separate, spread-relative check that boost cannot relax.
"""
from types import SimpleNamespace

import pytest

from silver_bullet.config import SilverBulletConfig
from silver_bullet.live_adapter import SilverBulletLiveAdapter
from silver_bullet.strategy import Signal
from trendline.config import TrendlineConfig
from trendline.live_adapter import TrendlineLiveAdapter
from trendline.strategy import Signal as TLSignal


EURUSD_SPREAD = 0.00008  # 8 points, as quoted live on Exness-MT5Trial9


def _adapter(mult: float = 1.5) -> SilverBulletLiveAdapter:
    cfg = SilverBulletConfig()
    cfg.min_stop_spread_mult = mult
    adapter = SilverBulletLiveAdapter(cfg, symbol="EURUSDm")
    adapter._digits = 5
    return adapter


def _signal(entry: float, stop: float) -> Signal:
    return Signal(
        direction="long",
        entry_price=entry,
        stop_price=stop,
        target_price=entry + 0.0001,
        sweep_level=stop,
        sweep_bar=0,
        fvg_zone=None,
        fvg_bar=0,
        window_id=2,
    )


def _quoter(monkeypatch, module: str, bid: float):
    """Quote a fixed spread on one adapter, and let a test drop the tick."""
    def _quote(spread: float | None):
        tick = None if spread is None else SimpleNamespace(bid=bid, ask=bid + spread)
        monkeypatch.setattr(f"{module}.mt5_cache.symbol_info_tick", lambda symbol: tick)
    return _quote


@pytest.fixture
def quoted(monkeypatch):
    return _quoter(monkeypatch, "silver_bullet.live_adapter", bid=1.15500)


@pytest.fixture
def tl_quoted(monkeypatch):
    return _quoter(monkeypatch, "trendline.live_adapter", bid=157.659)


class TestRejects:
    def test_stop_inside_the_spread(self, quoted):
        # The live case: 4 points of stop against 8 points of spread.
        quoted(EURUSD_SPREAD)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.15451, 1.15447))

    def test_stop_between_one_and_the_configured_multiple(self, quoted):
        # 10 points clears the raw spread but not 1.5x it — still rejected,
        # since a stop that survives the fill by 2 points is not a trade.
        quoted(EURUSD_SPREAD)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.15510, 1.15500))


class TestAllows:
    def test_stop_beyond_the_multiple(self, quoted):
        # 20 points against a 12-point bar — a normal setup, untouched.
        quoted(EURUSD_SPREAD)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.15520, 1.15500)) is False

    def test_just_beyond_the_multiple(self, quoted):
        # 12.5 points against a 12-point threshold: the first setup that
        # clears it must trade, or the guard is really a wider floor than it
        # advertises. Not asserted at exactly 1.5x — subtracting two prices
        # near 1.155 lands a few parts in 1e17 either side of the threshold,
        # so an equality test there measures float representation, not intent.
        quoted(EURUSD_SPREAD)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.155125, 1.15500)) is False

    def test_disabled_by_zero(self, quoted):
        # The kill switch has to work on the worst case, not just a safe one.
        quoted(EURUSD_SPREAD)
        assert _adapter(mult=0)._stop_inside_spread("EURUSDm", _signal(1.15451, 1.15447)) is False

    def test_missing_tick_does_not_block_trading(self, quoted):
        # No quote means no evidence of a bad stop. Failing open matches every
        # other MT5 read in the adapter; failing closed would silently halt
        # entries on a cache miss.
        quoted(None)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.15451, 1.15447)) is False

    def test_zero_spread_does_not_block_trading(self, quoted):
        # A crossed or unquoted book reports 0; treating that as "everything is
        # inside the spread" would reject every signal on the symbol.
        quoted(0.0)
        assert _adapter()._stop_inside_spread("EURUSDm", _signal(1.15451, 1.15447)) is False


class TestBoostCannotRelaxIt:
    def test_boosted_config_leaves_the_guard_at_full_strength(self, quoted):
        # _boosted_cfg halves min_risk_points; the spread guard reads self._cfg
        # so the same signal stays rejected while the booster is active.
        quoted(EURUSD_SPREAD)
        adapter = _adapter()
        boosted = adapter._boosted_cfg(adapter._cfg)
        assert boosted.min_risk_points == adapter._cfg.min_risk_points * 0.5
        assert boosted.min_stop_spread_mult == adapter._cfg.min_stop_spread_mult
        assert adapter._stop_inside_spread("EURUSDm", _signal(1.15451, 1.15447))


# ── Trendline ────────────────────────────────────────────────────────────────
# Same guard, different adapter. TL's exposure is the rollover rather than a
# halved floor: USDJPYm quotes ~10 points intraday and was observed at 130
# across the rollover, against a 23-point min_risk_points from TL_TARGETS.

USDJPY_ROLLOVER_SPREAD = 0.130  # 130 points, observed live at 13:53


def _tl_adapter(mult: float = 1.5) -> TrendlineLiveAdapter:
    cfg = TrendlineConfig()
    cfg.min_stop_spread_mult = mult
    return TrendlineLiveAdapter(cfg, symbol="USDJPYm")


def _tl_signal(entry: float, stop: float) -> TLSignal:
    return TLSignal(
        direction="long",
        entry_price=entry,
        stop_price=stop,
        target_price=entry + 0.2,
        line_kind="support",
        line_anchor1_bar=0,
        line_anchor2_bar=1,
        touch_bar=2,
        pattern="bullish",
    )


class TestTrendline:
    def test_rejects_stop_inside_the_rollover_spread(self, tl_quoted):
        # A 50-point stop is a normal TL setup intraday and is swallowed whole
        # by the rollover spread.
        tl_quoted(USDJPY_ROLLOVER_SPREAD)
        assert _tl_adapter()._stop_inside_spread("USDJPYm", _tl_signal(157.709, 157.659))

    def test_allows_the_same_stop_at_the_intraday_spread(self, tl_quoted):
        # 50 points against the usual 10-point spread — untouched. The guard
        # has to be a function of live conditions, not of the symbol.
        tl_quoted(0.010)
        assert _tl_adapter()._stop_inside_spread("USDJPYm", _tl_signal(157.709, 157.659)) is False

    def test_disabled_by_zero(self, tl_quoted):
        tl_quoted(USDJPY_ROLLOVER_SPREAD)
        assert _tl_adapter(mult=0)._stop_inside_spread("USDJPYm", _tl_signal(157.709, 157.659)) is False

    def test_missing_tick_does_not_block_trading(self, tl_quoted):
        tl_quoted(None)
        assert _tl_adapter()._stop_inside_spread("USDJPYm", _tl_signal(157.709, 157.659)) is False

    def test_boost_cannot_relax_it(self, tl_quoted):
        tl_quoted(USDJPY_ROLLOVER_SPREAD)
        adapter = _tl_adapter()
        boosted = adapter._boosted_cfg(adapter._cfg)
        assert boosted.min_risk_points == adapter._cfg.min_risk_points * 0.5
        assert boosted.min_stop_spread_mult == adapter._cfg.min_stop_spread_mult
        assert adapter._stop_inside_spread("USDJPYm", _tl_signal(157.709, 157.659))
