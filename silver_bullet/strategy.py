"""
Signal generation: converts indicator outputs into pending trade parameters.

Kept strictly decoupled from execution; all it returns is a description of
WHAT trade to take and WHERE to place entry/stop/target.  The backtest (or a
future broker adapter) decides HOW to place and manage the order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from .config import SilverBulletConfig
from .indicators import (
    detect_buyside_sweep,
    detect_sellside_sweep,
    detect_bullish_fvg,
    detect_bearish_fvg,
    fvg_entry_price,
    nearest_buyside_liquidity,
    nearest_sellside_liquidity,
)


@dataclass
class Signal:
    """A fully-specified setup ready for execution."""
    direction: str            # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float
    sweep_level: float        # level that was swept to trigger the bias
    sweep_bar: int            # bar index where the sweep occurred
    fvg_zone: Tuple[float, float]  # (bottom, top) of the FVG
    fvg_bar: int              # bar index where the FVG was identified
    window_id: int


@dataclass
class _SessionState:
    """Internal mutable state for one (date, window_id) session."""
    bias: Optional[str] = None         # None | "bullish" | "bearish"
    sweep_level: Optional[float] = None
    sweep_bar: Optional[int] = None
    signal_emitted: bool = False       # True once we've emitted a signal


def _compute_target(
    direction: str,
    entry: float,
    stop: float,
    highs: np.ndarray,
    lows: np.ndarray,
    current_bar: int,
    cfg: SilverBulletConfig,
) -> float:
    """Return the target price based on cfg.target_mode."""
    risk = abs(entry - stop)

    if cfg.target_mode == "rr":
        if direction == "long":
            return entry + cfg.rr * risk
        else:
            return entry - cfg.rr * risk

    # opposite_liquidity — fall back to rr if no pool found
    if direction == "long":
        lvl = nearest_buyside_liquidity(highs, current_bar, cfg.swing_lookback, entry)
    else:
        lvl = nearest_sellside_liquidity(lows, current_bar, cfg.swing_lookback, entry)

    if lvl is not None:
        return lvl

    # Fallback: fixed R:R
    if direction == "long":
        return entry + cfg.rr * risk
    else:
        return entry - cfg.rr * risk


class SignalGenerator:
    """
    Stateful bar-by-bar signal scanner.

    Call .on_bar(bar_idx, highs, lows, closes, opens, in_window, window_id)
    at each bar close.  Returns a Signal if a setup is complete, else None.
    """

    def __init__(self, cfg: SilverBulletConfig):
        self._cfg = cfg
        # Key: (date_str, window_id) → _SessionState
        self._sessions: dict[tuple, _SessionState] = {}

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
        in_window: bool,
        window_id: int,
        date_str: str,
        prev_day_bias: int = 0,
    ) -> Optional[Signal]:
        """Process one closed bar.  Return a Signal or None."""
        if not in_window:
            return None

        cfg = self._cfg
        key = (date_str, window_id)
        if key not in self._sessions:
            self._sessions[key] = _SessionState()
        sess = self._sessions[key]

        # One trade (signal) per window — already emitted
        if cfg.one_trade_per_window and sess.signal_emitted:
            return None

        # --- Step 1: detect sweep to establish bias ---
        if sess.bias is None:
            level = detect_sellside_sweep(
                lows, closes, bar_idx, cfg.swing_lookback, cfg.sweep_lookback
            )
            if level is not None:
                sess.bias = "bullish"
                sess.sweep_level = level
                sess.sweep_bar = bar_idx
                self._log(f"[SB] Sweep BULLISH | swept low={level:.2f} | bar={bar_idx} | {date_str} w{window_id}")
            else:
                level = detect_buyside_sweep(
                    highs, closes, bar_idx, cfg.swing_lookback, cfg.sweep_lookback
                )
                if level is not None:
                    sess.bias = "bearish"
                    sess.sweep_level = level
                    sess.sweep_bar = bar_idx
                    self._log(f"[SB] Sweep BEARISH | swept high={level:.2f} | bar={bar_idx} | {date_str} w{window_id}")

        # --- Step 2: once biased, look for a confirming FVG ---
        if sess.bias is None:
            return None

        # Require at least 1 bar after the sweep before accepting a FVG.
        # The sweep candle itself is not confirmation — the reversal needs to
        # start moving before we place a limit order into the gap.
        if bar_idx <= sess.sweep_bar:
            return None

        if sess.bias == "bullish":
            fvg = detect_bullish_fvg(highs, lows, bar_idx, cfg.fvg_min_points)
        else:
            fvg = detect_bearish_fvg(highs, lows, bar_idx, cfg.fvg_min_points)

        if fvg is None:
            return None

        self._log(f"[SB] FVG {sess.bias.upper()} | zone={fvg[0]:.2f}–{fvg[1]:.2f} | bar={bar_idx} | {date_str} w{window_id}")

        # --- Step 3: build the full signal ---
        bottom, top = fvg
        direction = "long" if sess.bias == "bullish" else "short"

        entry = fvg_entry_price(bottom, top, sess.bias, cfg.entry_in_fvg)

        if direction == "long":
            stop = sess.sweep_level - cfg.stop_buffer_points
        else:
            stop = sess.sweep_level + cfg.stop_buffer_points

        # Daily bias filter — align with previous day's completed candle direction.
        # prev_day_bias +1 = yesterday bullish → only take longs today.
        # prev_day_bias -1 = yesterday bearish → only take shorts today.
        # prev_day_bias  0 = first day or flat candle → no filter applied.
        if cfg.use_daily_bias and prev_day_bias != 0:
            if direction == "long"  and prev_day_bias == -1:
                return None
            if direction == "short" and prev_day_bias == 1:
                return None

        # Sanity: entry must be on the correct side of the stop
        if direction == "long" and entry <= stop:
            return None
        if direction == "short" and entry >= stop:
            return None

        # Minimum risk guard — skips degenerate setups where FVG nearly touches stop
        risk_points = abs(entry - stop)
        if risk_points < cfg.min_risk_points:
            return None

        target = _compute_target(direction, entry, stop, highs, lows, bar_idx, cfg)

        signal = Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            sweep_level=sess.sweep_level,
            sweep_bar=sess.sweep_bar,
            fvg_zone=fvg,
            fvg_bar=bar_idx,
            window_id=window_id,
        )

        if cfg.one_trade_per_window:
            sess.signal_emitted = True

        return signal

    def reset_session(self, date_str: str, window_id: int) -> None:
        """Explicitly clear state for a session (e.g. after a trade is taken)."""
        key = (date_str, window_id)
        if key in self._sessions:
            del self._sessions[key]
