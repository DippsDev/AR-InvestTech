"""
MT5 broker/trade-server clocks are not guaranteed to be true UTC. Confirmed
on AtlasFunded-Server: its clock runs ~3 hours ahead of real UTC. Every
timestamp MT5 returns (bar time, tick time, deal time) is stamped in that
server clock, even though the API/pandas labels it "UTC" — left uncorrected,
this silently shifts every downstream NY-session-window, news-day-by-date,
and daily trade/loss count by the broker's offset.

get_broker_utc_offset() measures the live offset from a current tick each
time it's called, rather than hardcoding a fixed number of hours, so it
self-corrects if the broker's offset changes (DST, server migration, etc).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5


def get_broker_utc_offset(symbol: str) -> timedelta:
    """How far ahead (positive) or behind (negative) of true UTC this
    broker's server clock currently is, measured from a live tick.

    Returns timedelta(0) if no tick is available — callers should treat
    that as "uncorrected this cycle", not "confirmed zero offset".
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return timedelta(0)
    broker_time = datetime.fromtimestamp(tick.time, tz=timezone.utc)
    return broker_time - datetime.now(timezone.utc)
