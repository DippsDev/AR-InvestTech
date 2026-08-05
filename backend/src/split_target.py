"""Shared helpers for the two-target (TP1/TP2) position split.

All three strategies express the split identically — `tp1_fraction` of the
position closes at `tp1_rr`, the remainder rides to `tp2_rr`, both halves
sharing one stop — so the arithmetic lives here rather than being reimplemented
three times. The strategies stay decoupled in every other respect; this module
holds no strategy state and imports nothing from them.
"""
from __future__ import annotations


def r_target(direction: str, entry: float, risk: float, rr: float) -> float:
    """Price sitting `rr` R away from `entry` in the profitable direction.

    `risk` is the absolute entry-to-stop distance, so it is always positive and
    the sign is carried by `direction` alone.
    """
    return entry + rr * risk if direction == "long" else entry - rr * risk


def split_lots(
    lots: float,
    tp1_fraction: float,
    volume_min: float,
    volume_step: float,
) -> tuple[float, float] | None:
    """Split `lots` into (tp1_leg, tp2_leg) on the broker's volume grid.

    Returns None when the position cannot be split — either leg landing below
    `volume_min` after snapping to `volume_step` means the broker would reject
    it. That is the normal case on a small account, where `_compute_lots` has
    already floored the whole position at `volume_min`: half of the minimum lot
    does not exist. Callers must handle None by placing one undivided order
    rather than by silently rounding a leg up, which would double the intended
    risk.
    """
    if volume_step <= 0 or volume_min <= 0:
        return None

    leg1 = round(lots * tp1_fraction / volume_step) * volume_step
    leg1 = round(leg1, 8)          # kill float dust from the division
    leg2 = round(lots - leg1, 8)

    if leg1 < volume_min or leg2 < volume_min:
        return None
    return leg1, leg2


def validate_split(tp1_rr: float, tp2_rr: float, tp1_fraction: float) -> None:
    """Raise if a split configuration is incoherent.

    Called once at generator construction rather than per signal. TP2 must sit
    strictly beyond TP1: if they were equal the second leg would fill at the
    same instant as the first and the split would be a no-op with two lots of
    commission, and if TP2 were nearer the legs would fill out of order and the
    "remainder rides further" contract would silently invert.
    """
    if not 0.0 < tp1_fraction < 1.0:
        raise ValueError(
            f"tp1_fraction must be strictly between 0 and 1, got {tp1_fraction}. "
            "Use split_targets=False for a single undivided target."
        )
    if tp1_rr <= 0 or tp2_rr <= 0:
        raise ValueError(f"tp1_rr and tp2_rr must be positive, got {tp1_rr} and {tp2_rr}")
    if tp2_rr <= tp1_rr:
        raise ValueError(
            f"tp2_rr ({tp2_rr}) must be strictly greater than tp1_rr ({tp1_rr}) — "
            "TP2 is the runner and has to sit beyond TP1."
        )
