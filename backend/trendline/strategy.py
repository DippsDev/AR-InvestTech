"""
Signal generation: converts trendline + candlestick indicators into pending
trade parameters.

Kept strictly decoupled from execution; all it returns is a description of
WHAT trade to take and WHERE to place entry/stop/target. The live adapter
(or a future backtester) decides HOW to place and manage the order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from silver_bullet.news_calendar import is_news_day

from .candlesticks import classify_reversal
from .config import TrendlineConfig
from .indicators import (
    TrendLine,
    build_resistance_line,
    build_support_line,
    check_breach,
    check_touch,
    is_same_line,
    nearest_buyside_liquidity,
    nearest_sellside_liquidity,
)


@dataclass
class Signal:
    """A fully-specified setup ready for execution."""
    direction: str              # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float
    line_kind: str               # "support" | "resistance"
    line_anchor1_bar: int
    line_anchor2_bar: int
    touch_bar: int
    pattern: str                 # confirming reversal-candlestick pattern name


class SignalGenerator:
    """
    Stateful bar-by-bar signal scanner.

    Call .on_bar(bar_idx, highs, lows, closes, opens, date_str) at each H1
    bar close. Returns a Signal if a setup is complete, else None.

    Unlike silver_bullet's SignalGenerator there are no session windows —
    EURUSD trades ~24/5 — so state is a single running support/resistance
    line pair plus a one-trade-at-a-time gate, not a per-session dict.
    """

    def __init__(self, cfg: TrendlineConfig):
        self._cfg = cfg
        self._support_line: Optional[TrendLine] = None
        self._resistance_line: Optional[TrendLine] = None
        self._trade_active: bool = False

    def _log(self, msg: str) -> None:
        from src.logger import logger
        logger.info(msg)

    def on_bar(
        self,
        bar_idx: int,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        opens: np.ndarray,
        date_str: str,
    ) -> Optional[Signal]:
        """Process one closed H1 bar. Return a Signal or None."""
        cfg = self._cfg

        if cfg.skip_news_days and is_news_day(date_str):
            return None
        if cfg.one_trade_at_a_time and self._trade_active:
            return None

        # --- Step 1: rebuild candidate lines from confirmed swings ---
        # Only replace the tracked line if the anchors actually changed, so an
        # unrelated recompute doesn't reset broken/broken_bar state, and a
        # rejected candidate (obstructed/too steep) doesn't clobber an
        # already-valid line.
        new_support = build_support_line(
            lows, highs, bar_idx, cfg.swing_lookback, cfg.avg_range_lookback,
            cfg.steepness_max_ratio, cfg.obstruction_tolerance_points,
        )
        if new_support is not None and not is_same_line(self._support_line, new_support):
            self._support_line = new_support

        new_resistance = build_resistance_line(
            lows, highs, bar_idx, cfg.swing_lookback, cfg.avg_range_lookback,
            cfg.steepness_max_ratio, cfg.obstruction_tolerance_points,
        )
        if new_resistance is not None and not is_same_line(self._resistance_line, new_resistance):
            self._resistance_line = new_resistance

        # --- Step 2: invalidate breached lines ---
        if self._support_line is not None and check_breach(
            self._support_line, bar_idx, float(closes[bar_idx]), cfg.breach_tolerance_points
        ):
            self._log(f"[TL] Support trendline broken | bar={bar_idx} | {date_str}")
            self._support_line = None

        if self._resistance_line is not None and check_breach(
            self._resistance_line, bar_idx, float(closes[bar_idx]), cfg.breach_tolerance_points
        ):
            self._log(f"[TL] Resistance trendline broken | bar={bar_idx} | {date_str}")
            self._resistance_line = None

        # --- Step 3: touch + reversal-candle confirmation -> signal ---
        pattern = classify_reversal(
            opens, highs, lows, closes, bar_idx,
            cfg.candle_body_ratio_max, cfg.candle_wick_ratio_min,
            cfg.railway_length_ratio_min, cfg.avg_body_lookback,
        )
        if pattern is None:
            return None

        if pattern == "bullish" and self._support_line is not None:
            if check_touch(self._support_line, bar_idx, float(highs[bar_idx]),
                            float(lows[bar_idx]), cfg.touch_tolerance_points):
                return self._build_signal(
                    "long", self._support_line, bar_idx, highs, lows, closes, pattern, date_str
                )

        if pattern == "bearish" and self._resistance_line is not None:
            if check_touch(self._resistance_line, bar_idx, float(highs[bar_idx]),
                            float(lows[bar_idx]), cfg.touch_tolerance_points):
                return self._build_signal(
                    "short", self._resistance_line, bar_idx, highs, lows, closes, pattern, date_str
                )

        return None

    def _build_signal(
        self,
        direction: str,
        line: TrendLine,
        bar_idx: int,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        pattern: str,
        date_str: str,
    ) -> Optional[Signal]:
        cfg = self._cfg
        entry = float(closes[bar_idx])  # aggressive: market order at bar close

        if direction == "long":
            stop = float(lows[bar_idx]) - cfg.stop_buffer_points
        else:
            stop = float(highs[bar_idx]) + cfg.stop_buffer_points

        risk = abs(entry - stop)
        if risk < cfg.min_risk_points:
            self._log(
                f"[TL] Signal rejected | risk {risk:.5f} below minimum "
                f"{cfg.min_risk_points:.5f} | bar={bar_idx} | {date_str}"
            )
            return None

        target: Optional[float] = None
        if cfg.target_mode == "opposite_swing":
            if direction == "long":
                lvl = nearest_buyside_liquidity(highs, bar_idx, cfg.swing_lookback, entry)
            else:
                lvl = nearest_sellside_liquidity(lows, bar_idx, cfg.swing_lookback, entry)
            if lvl is not None:
                swing_r = abs(lvl - entry) / risk
                if swing_r >= cfg.min_rr_for_swing_target:
                    target = lvl
        if target is None:
            target = entry + cfg.rr * risk if direction == "long" else entry - cfg.rr * risk

        self._log(
            f"[TL] Signal {direction.upper()} | pattern={pattern} | entry={entry:.5f} "
            f"stop={stop:.5f} target={target:.5f} | bar={bar_idx} | {date_str}"
        )
        return Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            line_kind=line.kind,
            line_anchor1_bar=line.anchor1_bar,
            line_anchor2_bar=line.anchor2_bar,
            touch_bar=bar_idx,
            pattern=pattern,
        )

    def notify_trade_opened(self) -> None:
        """Called by the live adapter once a signal has actually resulted in
        a filled order — sets the one-trade-at-a-time gate.

        Deliberately NOT set inside _build_signal: a signal can be built but
        then fail to place (e.g. lot-sizing rejects it for insufficient
        balance). If the gate were set on signal construction alone, a
        placement failure would permanently freeze this generator with no
        open position ever able to call notify_trade_closed()."""
        self._trade_active = True

    def notify_trade_closed(self) -> None:
        """Called by the live adapter once a position is fully closed —
        clears the one-trade-at-a-time gate."""
        self._trade_active = False
