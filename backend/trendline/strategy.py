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
from src.split_target import r_target as _r_target, validate_split

from .candlesticks import classify_reversal
from .config import TrendlineConfig
from .indicators import (
    TrendLine,
    build_resistance_line,
    build_resistance_line_from_swings,
    build_support_line,
    build_support_line_from_swings,
    check_breach,
    check_touch,
    is_same_line,
    is_swing_high,
    is_swing_low,
    nearest_buyside_liquidity,
    nearest_sellside_liquidity,
)


@dataclass
class Signal:
    """A fully-specified setup ready for execution."""
    direction: str              # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float          # TP1 when split_targets is on, else the only target
    line_kind: str               # "support" | "resistance"
    line_anchor1_bar: int
    line_anchor2_bar: int
    touch_bar: int
    pattern: str                 # confirming reversal-candlestick pattern name
    target_price_2: Optional[float] = None   # TP2; None when not splitting


class SignalGenerator:
    """
    Stateful bar-by-bar signal scanner.

    Call .on_bar(bar_idx, highs, lows, closes, opens, date_str) at each H1
    bar close. Returns a Signal if a setup is complete, else None.

    Unlike silver_bullet's SignalGenerator there are no session windows —
    US30 trades near-continuously — so state is a single running
    support/resistance line pair plus a one-trade-at-a-time gate, not a
    per-session dict.
    """

    def __init__(self, cfg: TrendlineConfig, *, incremental_swings: bool = False):
        if cfg.split_targets:
            validate_split(cfg.tp1_rr, cfg.tp2_rr, cfg.tp1_fraction)
        self._cfg = cfg
        self._support_line: Optional[TrendLine] = None
        self._resistance_line: Optional[TrendLine] = None
        self._trade_active: bool = False
        self._incremental_swings = incremental_swings
        self._last_swing_scan_bar = -1
        self._swing_highs: list[tuple[int, float]] = []
        self._swing_lows: list[tuple[int, float]] = []

    def _log(self, msg: str, level: str = "info") -> None:
        from src.logger import logger
        getattr(logger, level)(msg)

    @staticmethod
    def _remember_swing(swings: list[tuple[int, float]], swing: tuple[int, float]) -> None:
        swings.append(swing)
        if len(swings) > 2:
            del swings[0]

    def _advance_swing_cache(
        self,
        bar_idx: int,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> None:
        """Record swings as their right-hand confirmation bar closes.

        Backtests may skip calls while a trade is open, so this catches up all
        intervening bars. Only the latest two swings of each kind are needed.
        """
        if bar_idx < self._last_swing_scan_bar:
            self._last_swing_scan_bar = -1
            self._swing_highs.clear()
            self._swing_lows.clear()

        lookback = self._cfg.swing_lookback
        for confirmed_at in range(self._last_swing_scan_bar + 1, bar_idx + 1):
            center = confirmed_at - lookback
            if center < lookback:
                continue
            visible_highs = highs[: confirmed_at + 1]
            visible_lows = lows[: confirmed_at + 1]
            if is_swing_high(visible_highs, center, lookback):
                self._remember_swing(self._swing_highs, (center, float(highs[center])))
            if is_swing_low(visible_lows, center, lookback):
                self._remember_swing(self._swing_lows, (center, float(lows[center])))
        self._last_swing_scan_bar = max(self._last_swing_scan_bar, bar_idx)

    def _candidate_lines(
        self,
        bar_idx: int,
        highs: np.ndarray,
        lows: np.ndarray,
    ) -> tuple[Optional[TrendLine], Optional[TrendLine]]:
        cfg = self._cfg
        if not self._incremental_swings:
            return (
                build_support_line(
                    lows, highs, bar_idx, cfg.swing_lookback, cfg.avg_range_lookback,
                    cfg.steepness_max_ratio, cfg.obstruction_tolerance_points,
                ),
                build_resistance_line(
                    lows, highs, bar_idx, cfg.swing_lookback, cfg.avg_range_lookback,
                    cfg.steepness_max_ratio, cfg.obstruction_tolerance_points,
                ),
            )

        self._advance_swing_cache(bar_idx, highs, lows)
        support = None
        resistance = None
        if len(self._swing_lows) == 2:
            support = build_support_line_from_swings(
                lows, highs, bar_idx, self._swing_lows[0], self._swing_lows[1],
                cfg.avg_range_lookback, cfg.steepness_max_ratio,
                cfg.obstruction_tolerance_points,
            )
        if len(self._swing_highs) == 2:
            resistance = build_resistance_line_from_swings(
                lows, highs, bar_idx, self._swing_highs[0], self._swing_highs[1],
                cfg.avg_range_lookback, cfg.steepness_max_ratio,
                cfg.obstruction_tolerance_points,
            )
        return support, resistance

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
        new_support, new_resistance = self._candidate_lines(bar_idx, highs, lows)
        if new_support is not None and not is_same_line(self._support_line, new_support):
            self._support_line = new_support

        if new_resistance is not None and not is_same_line(self._resistance_line, new_resistance):
            self._resistance_line = new_resistance

        # --- Step 2: invalidate breached lines ---
        if self._support_line is not None and check_breach(
            self._support_line, bar_idx, float(closes[bar_idx]), cfg.breach_tolerance_points
        ):
            self._log(f"[TL] Support trendline broken | bar={bar_idx} | {date_str}", level="debug")
            self._support_line = None

        if self._resistance_line is not None and check_breach(
            self._resistance_line, bar_idx, float(closes[bar_idx]), cfg.breach_tolerance_points
        ):
            self._log(f"[TL] Resistance trendline broken | bar={bar_idx} | {date_str}", level="debug")
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
                f"{cfg.min_risk_points:.5f} | bar={bar_idx} | {date_str}",
                level="debug",
            )
            return None

        target_2: Optional[float] = None
        if cfg.split_targets:
            # Pure R multiples — the opposite-swing lookup is skipped entirely,
            # since a split needs two ordered targets and a single swing level
            # gives only one.
            target = _r_target(direction, entry, risk, cfg.tp1_rr)
            target_2 = _r_target(direction, entry, risk, cfg.tp2_rr)
        else:
            target = None
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
                target = _r_target(direction, entry, risk, cfg.rr)

        tp2_txt = f" target2={target_2:.5f}" if target_2 is not None else ""
        self._log(
            f"[TL] Signal {direction.upper()} | pattern={pattern} | entry={entry:.5f} "
            f"stop={stop:.5f} target={target:.5f}{tp2_txt} | bar={bar_idx} | {date_str}"
        )
        return Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            target_price_2=target_2,
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
