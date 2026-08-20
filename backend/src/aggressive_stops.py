"""Aggressive-mode stop overlay.

The live strategies place the initial stop on the sweep (Silver Bullet) or
the reversal-candle extreme (Trendline / Mutanabby), plus a tiny
volatility-scaled buffer. Silver Bullet then yanks that stop to entry at
0.25R. The result in live trading is a stop-out on the retest, then the
move that was predicted.

Aggressive mode already adds London windows and looser filters. This module
is the matching stop overlay: more air beyond the invalidation, and (where
the strategy already manages stops) later breakeven / a wider trail.

Dollar risk is unchanged. A wider stop just sizes a smaller lot, because
sizing divides the risk budget by entry-to-stop distance.

Applied in bot.py after per-symbol SB_TARGETS / TL_TARGETS / MB_TARGETS
overrides, so the multiplier lands on the scaled buffer rather than being
clobbered by it. Off when SB_AGGRESSIVE is false.
"""
from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

# Beyond the sweep / touching candle. 8× turns the scaled US30 1.5-point
# buffer into roughly a third of a median M5 bar — enough to clear a
# typical wick through the level without becoming an ATR-style stop.
STOP_BUFFER_MULT = 8.0

# Mutanabby has no point-buffer; its stop is candle extreme ± ATR.
# Double that air. Do not reuse STOP_BUFFER_MULT — 8× ATR is a different trade.
ATR_RISK_MULT = 2.0

# Trade management: the LOOSER arm from backtests/loosen_stops_compare.py.
# Only applied where the strategy already manages stops (breakeven_r > 0);
# Mutanabby's flat stop-or-target ride is left alone.
BREAKEVEN_R = 0.75
TRAIL_R = 0.5
EARLY_EXIT_R = 0.0
DEEP_PROFIT_R = 3.0
DEEP_TRAIL_R = 0.5

T = TypeVar("T")


def apply_aggressive_stops(cfg: T) -> T:
    """Return a copy of `cfg` with wider stops and looser management.

    Never tightens a knob that is already looser than this overlay, and
    never turns management on for a strategy that ships with it off.
    """
    updates: dict = {}

    if hasattr(cfg, "stop_buffer_points"):
        updates["stop_buffer_points"] = cfg.stop_buffer_points * STOP_BUFFER_MULT
    if hasattr(cfg, "atr_risk_multiplier"):
        updates["atr_risk_multiplier"] = cfg.atr_risk_multiplier * ATR_RISK_MULT

    if getattr(cfg, "breakeven_r", 0) > 0:
        updates["breakeven_r"] = max(cfg.breakeven_r, BREAKEVEN_R)
    if getattr(cfg, "trail_r", 0) > 0:
        updates["trail_r"] = max(cfg.trail_r, TRAIL_R)
    if getattr(cfg, "early_exit_r", 0) > 0:
        updates["early_exit_r"] = EARLY_EXIT_R
    if getattr(cfg, "deep_trail_r", 0) > 0:
        updates["deep_trail_r"] = max(cfg.deep_trail_r, DEEP_TRAIL_R)
    if getattr(cfg, "deep_profit_r", 0) > 0:
        updates["deep_profit_r"] = max(cfg.deep_profit_r, DEEP_PROFIT_R)

    # Off-hours uses its own management knobs on the same SilverBulletConfig.
    if getattr(cfg, "off_hours_breakeven_r", 0) > 0:
        updates["off_hours_breakeven_r"] = max(cfg.off_hours_breakeven_r, BREAKEVEN_R)
    if getattr(cfg, "off_hours_trail_r", 0) > 0:
        updates["off_hours_trail_r"] = max(cfg.off_hours_trail_r, TRAIL_R)
    if getattr(cfg, "off_hours_early_exit_r", 0) > 0:
        updates["off_hours_early_exit_r"] = EARLY_EXIT_R
    if getattr(cfg, "off_hours_deep_trail_r", 0) > 0:
        updates["off_hours_deep_trail_r"] = max(cfg.off_hours_deep_trail_r, DEEP_TRAIL_R)
    if getattr(cfg, "off_hours_deep_profit_r", 0) > 0:
        updates["off_hours_deep_profit_r"] = max(cfg.off_hours_deep_profit_r, DEEP_PROFIT_R)

    if not updates:
        return cfg
    return replace(cfg, **updates)
