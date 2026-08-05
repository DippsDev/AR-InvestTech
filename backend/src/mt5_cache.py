"""Per-loop-tick snapshot of the MT5 state every adapter reads identically.

The bot runs up to nine adapters per loop tick (3 strategies x 3 symbols, see
multi_symbol_targets.py) and every one of them independently asked MT5 for the
same things: `account_info()`, today's `history_deals_get()`, the open
`positions_get()` set, and per-symbol `symbol_info`/`symbol_info_tick`. Each of
those is a blocking IPC round-trip to the terminal, so nine adapters meant
~45 round-trips every 5 seconds to learn facts that are identical across all of
them.

This module fetches each fact at most once per loop tick and hands the same
result to every adapter. `begin_tick()` at the top of the loop drops the
previous tick's snapshot; the first caller to ask for a given fact pays for the
fetch and the other eight read it from memory.

What is deliberately NOT cached
-------------------------------
- Anything read back after an `order_send` (e.g. re-reading a position to
  confirm a stop moved). Those reads exist precisely to observe a change this
  cycle made, so they must hit MT5 directly. Use `invalidate_positions()` after
  a write to drop the stale position snapshot.
- `orders_get()` for pending-order fill detection — SB polls it only when it
  actually has pending orders, which is rare enough not to be worth caching and
  is fill-latency sensitive.

Thread safety
-------------
bridge.py serves the dashboard from FastAPI threads while the bot loop runs in
its own daemon thread, and both call into MT5. Every access here is guarded by
a re-entrant lock, and the cache is only ever *written* from whichever thread
asks first. Callers outside the bot loop (i.e. bridge.py) should keep calling
MT5 directly — they have their own request cadence and no tick boundary.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import MetaTrader5 as mt5

from . import broker_time

_LOCK = threading.RLock()

# Sentinel distinguishing "not fetched yet this tick" from "fetched, was None".
# MT5 legitimately returns None (no tick yet, terminal busy), and without this
# every adapter after the first would retry a call that already failed.
_MISSING = object()

# Facts identical for every adapter, fetched at most once per tick.
_account: Any = _MISSING
_deals: Any = _MISSING
_positions: Any = _MISSING

# Per-symbol facts, keyed by symbol.
_symbol_info: dict[str, Any] = {}
_symbol_tick: dict[str, Any] = {}

# Diagnostics: how many MT5 round-trips this tick actually made, and how many
# were served from the snapshot. Read by the bot's periodic perf log.
_fetches: int = 0
_hits: int = 0

# Lifetime totals, never reset by begin_tick.
_total_fetches: int = 0
_total_hits: int = 0


def begin_tick() -> None:
    """Drop the previous tick's snapshot. Call once at the top of each bot loop
    iteration, before any adapter cycles."""
    global _account, _deals, _positions, _fetches, _hits
    with _LOCK:
        _account = _MISSING
        _deals = _MISSING
        _positions = _MISSING
        _symbol_info.clear()
        _symbol_tick.clear()
        _fetches = 0
        _hits = 0


def _count(hit: bool) -> None:
    """Record a snapshot hit or an actual MT5 round-trip. Caller holds _LOCK."""
    global _fetches, _hits, _total_fetches, _total_hits
    if hit:
        _hits += 1
        _total_hits += 1
    else:
        _fetches += 1
        _total_fetches += 1


def account_info() -> Any:
    """Today's account snapshot — identical for every adapter."""
    global _account
    with _LOCK:
        if _account is _MISSING:
            _count(hit=False)
            _account = mt5.account_info()
        else:
            _count(hit=True)
        return _account


def positions_get(ticket: Optional[int] = None) -> list:
    """Open positions, from one `positions_get()` snapshot per tick.

    With `ticket`, filters that snapshot rather than issuing a per-ticket query
    — the adapters called `positions_get(ticket=...)` three or four times per
    open position per cycle (sync, status logging, breakeven, trail) and every
    one of those is the same underlying state.

    Returns a list (never None) so callers can drop their `or []` idiom.
    """
    global _positions
    with _LOCK:
        if _positions is _MISSING:
            _count(hit=False)
            _positions = mt5.positions_get()
        else:
            _count(hit=True)
        positions = _positions or []
        if ticket is None:
            return list(positions)
        return [p for p in positions if p.ticket == ticket]


def invalidate_positions() -> None:
    """Drop the cached position snapshot.

    Call after any `order_send` that changes position state (SL/TP moves,
    closes, new fills) so the next read observes the change instead of the
    pre-write snapshot.
    """
    global _positions
    with _LOCK:
        _positions = _MISSING


def history_deals_today(broker_utc_offset: timedelta, ny_tz) -> list:
    """Every deal since NY midnight, fetched once per tick and shared.

    All three strategies' daily circuit breakers want the same window and then
    filter it locally by symbol and magic/ticket, so the query itself is
    identical across adapters — this was nine copies of the single most
    expensive call in the loop.

    `broker_utc_offset` shifts the window into the broker's server clock (see
    src/broker_time.py). It is measured per adapter but is the same broker for
    all of them, so the first caller's offset defines the tick's window; a
    sub-second difference between adapters cannot move a NY-midnight boundary.
    """
    global _deals
    with _LOCK:
        if _deals is not _MISSING:
            _count(hit=True)
            return list(_deals or [])

        _count(hit=False)
        ny_midnight = datetime.now(ny_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from_date = ny_midnight.astimezone(timezone.utc) + broker_utc_offset
        to_date = datetime.now(timezone.utc) + broker_utc_offset
        try:
            _deals = mt5.history_deals_get(from_date, to_date)
        except Exception:
            # Callers treat an empty result as "no deals seen this tick" and
            # keep their previously computed daily totals, same as before.
            _deals = None
            raise
        return list(_deals or [])


def symbol_info(symbol: str) -> Any:
    """Contract details (digits, volume min/step/max, trade_mode).

    Cached per tick rather than indefinitely: trade_mode changes when a session
    opens or closes, and `_market_is_open` depends on reading that promptly.
    """
    with _LOCK:
        if symbol in _symbol_info:
            _count(hit=True)
            return _symbol_info[symbol]
        _count(hit=False)
        info = mt5.symbol_info(symbol)
        _symbol_info[symbol] = info
        return info


def symbol_info_tick(symbol: str) -> Any:
    """Latest tick for `symbol`, shared across this tick's adapters.

    Price-sensitive logic (breakeven triggers, trailing stops) reads this, so
    the cache lifetime is deliberately one loop tick and no longer: within a
    tick all adapters run in well under a second, and the loop re-reads every
    5 seconds exactly as it did before this cache existed.
    """
    with _LOCK:
        if symbol in _symbol_tick:
            _count(hit=True)
            return _symbol_tick[symbol]
        _count(hit=False)
        tick = mt5.symbol_info_tick(symbol)
        _symbol_tick[symbol] = tick
        return tick


def broker_utc_offset(symbol: str) -> timedelta:
    """Broker server-clock offset from true UTC, off the cached tick.

    Same measurement as src/broker_time.get_broker_utc_offset — and the same
    code — but reusing this tick's snapshot instead of issuing its own
    `symbol_info_tick` per adapter.
    """
    return broker_time.offset_from_tick(symbol_info_tick(symbol))


def tick_stats() -> tuple[int, int]:
    """(round-trips, snapshot hits) for the tick in progress."""
    with _LOCK:
        return _fetches, _hits


def lifetime_stats() -> tuple[int, int]:
    """(round-trips, snapshot hits) since process start."""
    with _LOCK:
        return _total_fetches, _total_hits
