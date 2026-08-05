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

from src.split_target import r_target, validate_split

from .config import SilverBulletConfig
from .news_calendar import is_news_day
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
    target_price: float       # TP1 when split_targets is on, else the only target
    sweep_level: float        # level that was swept to trigger the bias
    sweep_bar: int            # bar index where the sweep occurred
    fvg_zone: Tuple[float, float]  # (bottom, top) of the FVG
    fvg_bar: int              # bar index where the FVG was identified
    window_id: int
    target_price_2: Optional[float] = None   # TP2; None when not splitting


@dataclass
class _SessionState:
    """Internal mutable state for one (date, window_id) session."""
    bias: Optional[str] = None         # None | "bullish" | "bearish"
    sweep_level: Optional[float] = None
    sweep_bar: Optional[int] = None
    signal_emitted: bool = False       # True once we've emitted a signal


def _compute_targets(
    direction: str,
    entry: float,
    stop: float,
    highs: np.ndarray,
    lows: np.ndarray,
    current_bar: int,
    cfg: SilverBulletConfig,
) -> Tuple[float, Optional[float]]:
    """Return (TP1, TP2). TP2 is None unless cfg.split_targets is on.

    When splitting, both targets are pure R multiples and the liquidity lookup
    below is skipped — see the warning on `split_targets` in config.py for what
    that costs.
    """
    risk = abs(entry - stop)

    if cfg.split_targets:
        return (
            r_target(direction, entry, risk, cfg.tp1_rr),
            r_target(direction, entry, risk, cfg.tp2_rr),
        )

    return _single_target(direction, entry, stop, highs, lows, current_bar, cfg), None


def _single_target(
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

    # opposite_liquidity — fall back to rr if no pool found.
    #
    # The nearest pool is accepted however close it is, with no minimum
    # reward:risk floor. This looks wrong — the trade log contains setups
    # risking ~18 points to make ~1, and since the backtester fills at
    # `entry ± (slippage + spread/2)` while this target is computed from the
    # pre-cost entry, a few open already past their target and book a loss
    # recorded as a `target` exit. Adding a floor is nevertheless the wrong
    # fix: these near pools are quick high-probability scalps and they carry
    # almost all of the strategy's profit.
    #
    # Measured over the full ~17-month M5 history for all three live symbols
    # (DE30m/EURUSDm/GBPUSDm), with each symbol's own campaign costs. The
    # trade count is identical (156) in every arm — a floor does not filter
    # setups, it only relocates the target:
    #
    #     floor  0.00 (this code) : +$4,820 net, ~62% win rate
    #     floor  0.02             : +$3,518
    #     floor  0.10             : +$1,739
    #     floor  0.50 and above   : +$118 net,  ~46% win rate
    #
    # Trendline's min_rr_for_swing_target (3.0) guards the analogous rule for
    # that strategy; the asymmetry is intentional, so don't harmonise them.
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

    def __init__(self, cfg: SilverBulletConfig, digits: int = 2):
        if cfg.split_targets:
            validate_split(cfg.tp1_rr, cfg.tp2_rr, cfg.tp1_fraction)
        self._cfg = cfg
        # Decimal places for prices in log output. Defaults to 2 for indices;
        # the live adapter overrides it per symbol (see set_digits).
        self._digits = digits
        # Key: (date_str, window_id) → _SessionState
        self._sessions: dict[tuple, _SessionState] = {}

    def set_digits(self, digits: int) -> None:
        """Match log precision to the symbol MT5 reports.

        Formatting to a fixed 2dp renders every price on a 5-digit FX pair as
        the same number — entry, stop and target all print as "1.15" — which
        makes it impossible to check a fill against its signal or verify the
        R:R from the log. Indices are unaffected, which is why this survived
        US30-only development.
        """
        self._digits = digits

    def _p(self, value: float) -> str:
        """Format a price (or a price distance) at the symbol's precision."""
        return f"{value:.{self._digits}f}"

    def _log(self, msg: str, level: str = "info") -> None:
        from src.logger import logger
        getattr(logger, level)(msg)

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

        # Skip signal generation entirely on high-impact news days when configured.
        if cfg.skip_news_days and is_news_day(date_str):
            return None
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
                self._log(f"[SB] Sweep BULLISH | swept low={self._p(level)} | bar={bar_idx} | {date_str} w{window_id}", level="debug")
                if cfg.sweep_entry_mode:
                    return self._sweep_signal("long", closes[bar_idx], level, highs, lows, bar_idx, cfg, sess, window_id)
            else:
                level = detect_buyside_sweep(
                    highs, closes, bar_idx, cfg.swing_lookback, cfg.sweep_lookback
                )
                if level is not None:
                    sess.bias = "bearish"
                    sess.sweep_level = level
                    sess.sweep_bar = bar_idx
                    self._log(f"[SB] Sweep BEARISH | swept high={self._p(level)} | bar={bar_idx} | {date_str} w{window_id}", level="debug")
                    if cfg.sweep_entry_mode:
                        return self._sweep_signal("short", closes[bar_idx], level, highs, lows, bar_idx, cfg, sess, window_id)

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

        self._log(f"[SB] FVG {sess.bias.upper()} | zone={self._p(fvg[0])}–{self._p(fvg[1])} | bar={bar_idx} | {date_str} w{window_id}", level="debug")

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
                self._log(f"[SB] Signal rejected | daily bias mismatch (bearish yesterday) | bar={bar_idx} | {date_str} w{window_id}", level="debug")
                return None
            if direction == "short" and prev_day_bias == 1:
                self._log(f"[SB] Signal rejected | daily bias mismatch (bullish yesterday) | bar={bar_idx} | {date_str} w{window_id}", level="debug")
                return None

        # Sanity: entry must be on the correct side of the stop
        if direction == "long" and entry <= stop:
            self._log(f"[SB] Signal rejected | entry {self._p(entry)} not above stop {self._p(stop)} | bar={bar_idx} | {date_str} w{window_id}", level="debug")
            return None
        if direction == "short" and entry >= stop:
            self._log(f"[SB] Signal rejected | entry {self._p(entry)} not below stop {self._p(stop)} | bar={bar_idx} | {date_str} w{window_id}", level="debug")
            return None

        # Minimum risk guard — skips degenerate setups where FVG nearly touches stop
        risk_points = abs(entry - stop)
        if risk_points < cfg.min_risk_points:
            self._log(
                f"[SB] Signal rejected | risk {self._p(risk_points)}pts below minimum "
                f"{self._p(cfg.min_risk_points)}pts | bar={bar_idx} | {date_str} w{window_id}",
                level="debug",
            )
            return None

        target, target_2 = _compute_targets(direction, entry, stop, highs, lows, bar_idx, cfg)

        signal = Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            target_price_2=target_2,
            sweep_level=sess.sweep_level,
            sweep_bar=sess.sweep_bar,
            fvg_zone=fvg,
            fvg_bar=bar_idx,
            window_id=window_id,
        )

        if cfg.one_trade_per_window:
            sess.signal_emitted = True

        self._log(
            f"[SB] Signal {direction.upper()} | entry={self._p(entry)} stop={self._p(stop)} "
            f"target={self._p(target)} | sweep={self._p(sess.sweep_level)} "
            f"fvg={self._p(fvg[0])}-{self._p(fvg[1])} | bar={bar_idx} | {date_str} w{window_id}"
        )
        return signal

    def _sweep_signal(
        self,
        direction: str,
        entry: float,
        sweep_level: float,
        highs: np.ndarray,
        lows: np.ndarray,
        bar_idx: int,
        cfg: "SilverBulletConfig",
        sess: _SessionState,
        window_id: int,
    ) -> Optional[Signal]:
        """Return a signal based on the sweep bar alone (no FVG required)."""
        if direction == "long":
            stop = sweep_level - cfg.stop_buffer_points
        else:
            stop = sweep_level + cfg.stop_buffer_points

        if direction == "long" and entry <= stop:
            self._log(f"[SB] Sweep-entry rejected | entry {self._p(entry)} not above stop {self._p(stop)} | bar={bar_idx} w{window_id}", level="debug")
            return None
        if direction == "short" and entry >= stop:
            self._log(f"[SB] Sweep-entry rejected | entry {self._p(entry)} not below stop {self._p(stop)} | bar={bar_idx} w{window_id}", level="debug")
            return None

        risk = abs(entry - stop)
        if risk < cfg.min_risk_points:
            self._log(
                f"[SB] Sweep-entry rejected | risk {self._p(risk)}pts below minimum "
                f"{self._p(cfg.min_risk_points)}pts | bar={bar_idx} w{window_id}",
                level="debug",
            )
            return None

        if cfg.split_targets:
            target = r_target(direction, entry, risk, cfg.tp1_rr)
            target_2 = r_target(direction, entry, risk, cfg.tp2_rr)
        else:
            target = r_target(direction, entry, risk, cfg.rr)
            target_2 = None

        if cfg.one_trade_per_window:
            sess.signal_emitted = True

        self._log(
            f"[SB] Signal {direction.upper()} | entry={self._p(entry)} stop={self._p(stop)} "
            f"target={self._p(target)} | sweep={self._p(sweep_level)} (sweep-entry) | "
            f"bar={bar_idx} w{window_id}"
        )
        return Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            target_price_2=target_2,
            sweep_level=sweep_level,
            sweep_bar=bar_idx,
            fvg_zone=(entry, entry),
            fvg_bar=bar_idx,
            window_id=window_id,
        )

    def reset_session(self, date_str: str, window_id: int) -> None:
        """Explicitly clear state for a session (e.g. after a trade is taken)."""
        key = (date_str, window_id)
        if key in self._sessions:
            del self._sessions[key]
