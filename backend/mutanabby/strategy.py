"""
Signal generation: converts the indicator's SuperTrend/SMA/ATR series into
pending trade parameters.

Kept strictly decoupled from execution; all it returns is a description of
WHAT trade to take and WHERE to place entry/stop/target. The backtester (or a
future live adapter) decides HOW to place and manage the order.

Relationship to the Pine source
-------------------------------
    bull    = ta.crossover(close, supertrend)  and close >= sma9
    bear    = ta.crossunder(close, supertrend) and close <= sma9
    atrStop = trigger == 1 ? low - atrBand : high + atrBand
    tpNRl_y = (lastTrade(close) - lastTrade(atrStop)) * N + lastTrade(close)

`lastTrade(src)` is `ta.valuewhen(bull or bear, src, 0)` — the value at the most
recent signal bar — so entry/stop/target are all read off the signal bar, which
is what _build_signal does. `trigger` is just "is bull more recent than bear",
which on a signal bar reduces to the direction of that very signal.

The TP formula needs no sign special-casing: on a short, (entry - stop) is
negative, so entry + N*(entry - stop) projects downward correctly. That is the
source's behaviour and it is kept verbatim.

Why the indicators are precomputed
----------------------------------
SuperTrend is recursive, so recomputing it inside a per-bar callback would be
O(n^2) over 99k M5 bars. Every series in indicators.py is causal (value[i]
depends only on inputs at indices <= i), so computing them once up front and
reading index i inside on_bar() is exactly equivalent and look-ahead safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from silver_bullet.news_calendar import is_news_day
from src.split_target import validate_split

from .config import MutanabbyConfig
from .indicators import atr, crossover, crossunder, rsi, sma, supertrend


@dataclass
class Signal:
    """A fully-specified setup ready for execution."""
    direction: str              # "long" | "short"
    entry_price: float
    stop_price: float
    target_price: float         # TP1 when split_targets is on, else the only target
    bar_idx: int
    # --- Diagnostics (label text on the chart; gate nothing) ---
    strength: str               # "normal" | "strong"
    supertrend: float
    trend_sma: float
    rsi: float
    target_price_2: Optional[float] = None   # TP2; None when not splitting


class SignalGenerator:
    """
    Stateful bar-by-bar signal scanner.

    Unlike silver_bullet's (per-session state) or trendline's (running
    support/resistance lines), this one carries almost no state: the indicator
    is memoryless bar-to-bar once its series are computed. The only state is
    the one-trade-at-a-time gate, kept for interface parity with the other two
    strategies' generators.

    Construction computes every series over the full arrays, so pass the whole
    history once:

        gen = SignalGenerator(cfg, highs, lows, closes)
        for i in range(n):
            sig = gen.on_bar(i, date_str)
    """

    def __init__(self, cfg: MutanabbyConfig, highs: np.ndarray, lows: np.ndarray,
                 closes: np.ndarray):
        if cfg.split_targets:
            validate_split(cfg.tp1_rr, cfg.tp2_rr, cfg.tp1_fraction)
        self._cfg = cfg
        self._highs = np.asarray(highs, dtype=float)
        self._lows = np.asarray(lows, dtype=float)
        self._closes = np.asarray(closes, dtype=float)
        self._trade_active = False

        st, direction = supertrend(
            self._highs, self._lows, self._closes,
            cfg.sensitivity, cfg.supertrend_atr_length,
        )
        self._st = st
        self._direction = direction

        self._trend_sma = sma(self._closes, cfg.trend_sma_length)
        self._fast_sma = sma(self._closes, cfg.fast_sma_length)
        self._slow_sma = sma(self._closes, cfg.slow_sma_length)
        self._risk_atr = atr(self._highs, self._lows, self._closes, cfg.risk_atr_length)
        self._rsi = rsi(self._closes, cfg.rsi_length)

        # bull / bear exactly as the source defines them.
        self._bull = crossover(self._closes, st) & (self._closes >= self._trend_sma)
        self._bear = crossunder(self._closes, st) & (self._closes <= self._trend_sma)

    # ── Introspection (used by tests and by the backtester's diagnostics) ─────

    @property
    def bull(self) -> np.ndarray:
        return self._bull

    @property
    def bear(self) -> np.ndarray:
        return self._bear

    @property
    def supertrend_line(self) -> np.ndarray:
        return self._st

    def _log(self, msg: str, level: str = "info") -> None:
        from src.logger import logger
        getattr(logger, level)(msg)

    def on_bar(self, bar_idx: int, date_str: str) -> Optional[Signal]:
        """Process one closed bar. Return a Signal or None."""
        cfg = self._cfg

        if cfg.skip_news_days and is_news_day(date_str):
            return None
        if self._trade_active:
            return None

        if self._bull[bar_idx]:
            return self._build_signal("long", bar_idx, date_str)
        if self._bear[bar_idx]:
            return self._build_signal("short", bar_idx, date_str)
        return None

    def _strength(self, direction: str, bar_idx: int) -> str:
        """Reproduce the chart's Buy / Strong Buy label choice.

        The source reads, for a long:  sma4 >= sma5 ? "Buy" : "Strong Buy"
        i.e. the FASTER MA being above the slower one prints the *weaker*
        label. That is almost certainly inverted, so `legacy_strength_labels`
        selects between chart-faithful and sane. Either way this is a recorded
        diagnostic, never a filter — flip the flag and the trade list is
        identical apart from this field.
        """
        fast, slow = self._fast_sma[bar_idx], self._slow_sma[bar_idx]
        if np.isnan(fast) or np.isnan(slow):
            return "normal"
        if direction == "long":
            legacy_strong = fast < slow
        else:
            legacy_strong = fast > slow
        strong = legacy_strong if self._cfg.legacy_strength_labels else not legacy_strong
        return "strong" if strong else "normal"

    def _build_signal(self, direction: str, bar_idx: int, date_str: str) -> Optional[Signal]:
        cfg = self._cfg
        entry = float(self._closes[bar_idx])

        atr_band = self._risk_atr[bar_idx]
        if np.isnan(atr_band):
            return None
        atr_band *= cfg.atr_risk_multiplier

        if direction == "long":
            stop = float(self._lows[bar_idx]) - atr_band
        else:
            stop = float(self._highs[bar_idx]) + atr_band

        risk = abs(entry - stop)
        if risk <= 0:
            return None
        if cfg.min_risk_points > 0 and risk < cfg.min_risk_points:
            self._log(
                f"[MB] Signal rejected | risk {risk:.5f} below minimum "
                f"{cfg.min_risk_points:.5f} | bar={bar_idx} | {date_str}",
                level="debug",
            )
            return None

        # Source formula, sign-correct for both directions without branching:
        # on a short (entry - stop) is negative, so the projection runs downward.
        # The split reuses it for both rungs rather than switching to a helper,
        # keeping the TP maths identical to the Pine original.
        target_2: Optional[float] = None
        if cfg.split_targets:
            target = (entry - stop) * cfg.tp1_rr + entry
            target_2 = (entry - stop) * cfg.tp2_rr + entry
        else:
            target = (entry - stop) * cfg.rr + entry

        strength = self._strength(direction, bar_idx)
        tp2_txt = f" target2={target_2:.5f}" if target_2 is not None else ""
        self._log(
            f"[MB] Signal {direction.upper()} ({strength}) | entry={entry:.5f} "
            f"stop={stop:.5f} target={target:.5f}{tp2_txt} | bar={bar_idx} | {date_str}"
        )
        return Signal(
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            target_price_2=target_2,
            bar_idx=bar_idx,
            strength=strength,
            supertrend=float(self._st[bar_idx]),
            trend_sma=float(self._trend_sma[bar_idx]),
            rsi=float(self._rsi[bar_idx]) if not np.isnan(self._rsi[bar_idx]) else float("nan"),
        )

    def notify_trade_opened(self) -> None:
        """Called once a signal has actually resulted in a filled order.

        Deliberately NOT set inside _build_signal: a signal can be built and
        then fail to place (e.g. lot sizing rejects it), which would freeze the
        generator with no open position able to call notify_trade_closed().
        """
        self._trade_active = True

    def notify_trade_closed(self) -> None:
        self._trade_active = False
