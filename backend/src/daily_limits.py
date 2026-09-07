"""Shared daily circuit-breaker evaluation for SB / TL / MB live adapters.

Settings Risk Parameters are account-wide: max trades / day and daily loss
limit apply to the whole bot book (all strategies + symbols), not per symbol.

The adapters used to fail *open* when MT5 history could not be fetched (empty
deal list → daily_entries stayed 0 → cap never tripped). That let concurrent
stacking continue until the broker returned "No money".

This helper:
  1. Fails *closed* when today's deal history cannot be read.
  2. Attributes deals/positions by magic, recorded tickets, or order comment.
  3. Floors the entry count by open owned positions + process-wide placements
     so under-counted history cannot hide a stack already on the book.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import MetaTrader5 as mt5

from . import mt5_cache
from .ticket_store import load_tickets

# Live strategy markers — keep in sync with each live_adapter's MAGIC / comments.
BOT_MAGICS: tuple[int, ...] = (202406122, 202411001, 202507001)  # SB, TL, MB
BOT_STRATEGIES: tuple[str, ...] = ("SB", "TL", "MB")
BOT_COMMENT_PREFIXES: tuple[str, ...] = (
    "SilverBullet", "Trendline", "Mutanabby", "SB_", "TL_", "MB_",
)

_SESSION_LOCK = threading.Lock()
_SESSION_DATE: str = ""
_SESSION_ENTRIES: int = 0


@dataclass(frozen=True)
class DailyLimitVerdict:
    allowed: bool
    daily_entries: int
    daily_pnl: float
    open_owned: int
    reason: Optional[str] = None  # history_unavailable | loss_limit | trade_cap


def reset_session_entries(ny_date: str) -> None:
    """Reset the process-wide fill counter when the NY day rolls over."""
    global _SESSION_DATE, _SESSION_ENTRIES
    with _SESSION_LOCK:
        if _SESSION_DATE != ny_date:
            _SESSION_DATE = ny_date
            _SESSION_ENTRIES = 0


def note_entry_placed(count: int = 1, ny_date: Optional[str] = None) -> None:
    """Record fills this process just confirmed — floors the daily trade cap."""
    global _SESSION_DATE, _SESSION_ENTRIES
    with _SESSION_LOCK:
        if ny_date is not None and _SESSION_DATE != ny_date:
            _SESSION_DATE = ny_date
            _SESSION_ENTRIES = 0
        _SESSION_ENTRIES += max(0, int(count))


def session_entries_today() -> int:
    with _SESSION_LOCK:
        return _SESSION_ENTRIES


def _all_tickets(strategies: tuple[str, ...]) -> set[int]:
    tickets: set[int] = set()
    for strategy in strategies:
        tickets |= load_tickets(strategy=strategy)
    return tickets


def _owned(
    *,
    magics: tuple[int, ...],
    own_tickets: set[int],
    ticket: int,
    deal_magic: int,
    comment: str,
    comment_prefixes: tuple[str, ...],
) -> bool:
    if deal_magic in magics or ticket in own_tickets:
        return True
    if comment_prefixes and comment:
        return any(comment.startswith(prefix) for prefix in comment_prefixes)
    return False


def count_open_owned(
    *,
    magics: tuple[int, ...] = BOT_MAGICS,
    strategies: tuple[str, ...] = BOT_STRATEGIES,
    comment_prefixes: tuple[str, ...] = BOT_COMMENT_PREFIXES,
) -> int:
    """How many open MT5 positions belong to this bot (any strategy/symbol)."""
    own_tickets = _all_tickets(strategies)
    n = 0
    for pos in mt5_cache.positions_get():
        if _owned(
            magics=magics,
            own_tickets=own_tickets,
            ticket=int(pos.ticket),
            deal_magic=int(getattr(pos, "magic", 0) or 0),
            comment=str(getattr(pos, "comment", "") or ""),
            comment_prefixes=comment_prefixes,
        ):
            n += 1
    return n


def evaluate_daily_limits(
    *,
    broker_utc_offset: timedelta,
    ny_tz,
    max_trades: int,
    loss_limit_usd: float,
    session_entries: Optional[int] = None,
    magics: tuple[int, ...] = BOT_MAGICS,
    strategies: tuple[str, ...] = BOT_STRATEGIES,
    comment_prefixes: tuple[str, ...] = BOT_COMMENT_PREFIXES,
) -> DailyLimitVerdict:
    """Return whether a new entry is allowed for the whole bot book today."""
    if session_entries is None:
        session_entries = session_entries_today()

    open_owned = count_open_owned(
        magics=magics, strategies=strategies, comment_prefixes=comment_prefixes
    )

    try:
        deals = mt5_cache.history_deals_today(broker_utc_offset, ny_tz)
    except Exception:
        return DailyLimitVerdict(
            allowed=False,
            daily_entries=max(0, session_entries, open_owned),
            daily_pnl=0.0,
            open_owned=open_owned,
            reason="history_unavailable",
        )

    own_tickets = _all_tickets(strategies)
    daily_pnl = 0.0
    history_entries = 0
    for deal in deals:
        if not _owned(
            magics=magics,
            own_tickets=own_tickets,
            ticket=int(getattr(deal, "position_id", 0) or 0),
            deal_magic=int(getattr(deal, "magic", 0) or 0),
            comment=str(getattr(deal, "comment", "") or ""),
            comment_prefixes=comment_prefixes,
        ):
            continue
        if deal.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
            daily_pnl += float(deal.profit) + float(deal.commission) + float(deal.swap)
            if deal.entry == mt5.DEAL_ENTRY_IN:
                history_entries += 1

    # Floors: history can under-count; open book + this process's placements cannot.
    daily_entries = max(history_entries, open_owned, max(0, session_entries))

    if daily_pnl <= -abs(loss_limit_usd):
        return DailyLimitVerdict(
            allowed=False,
            daily_entries=daily_entries,
            daily_pnl=daily_pnl,
            open_owned=open_owned,
            reason="loss_limit",
        )

    if daily_entries >= max_trades:
        return DailyLimitVerdict(
            allowed=False,
            daily_entries=daily_entries,
            daily_pnl=daily_pnl,
            open_owned=open_owned,
            reason="trade_cap",
        )

    return DailyLimitVerdict(
        allowed=True,
        daily_entries=daily_entries,
        daily_pnl=daily_pnl,
        open_owned=open_owned,
        reason=None,
    )
