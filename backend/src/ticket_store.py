"""Local record of MT5 position tickets this bot has opened.

Some brokers (seen on AtlasFunded-Server) zero out the `magic` field on
deals regardless of what was set on the order, which breaks matching this
bot's trades against MT5 history by magic number alone. This module gives
callers a broker-independent fallback: every ticket the bot itself confirms
opening is recorded here (tagged with which strategy opened it), and
history lookups can match against that set instead of (or in addition to)
magic. `load_tickets(strategy=...)` lets Silver Bullet's and Trendline's own
daily circuit breakers each see only their own tickets even when magic is
unreliable; `load_tickets()` with no filter (used by the dashboard's
combined trade history) returns everything regardless of strategy or
entry format (old plain-timestamp entries included).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from . import paths

_LOCK = threading.Lock()
_RETENTION_DAYS = 35  # a little past the 30-day history window callers use


def _store_path():
    return paths.app_data_dir() / "bot_tickets.json"


def _load_raw() -> dict:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_ticket(ticket: int, strategy: str | None = None) -> None:
    """Record that the bot opened `ticket`, optionally tagged with which
    strategy ("SB" or "TL") opened it. Safe to call from any thread."""
    with _LOCK:
        data = _load_raw()
        data[str(ticket)] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "strategy": strategy,
        }

        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        data = {
            t: entry for t, entry in data.items()
            if _safe_parse(_entry_ts(entry)) is None or _safe_parse(_entry_ts(entry)) >= cutoff
        }

        _store_path().write_text(json.dumps(data), encoding="utf-8")


def load_tickets(strategy: str | None = None) -> set[int]:
    """Return the set of position tickets the bot has opened.

    With no `strategy`, returns every recorded ticket (any strategy, plus
    legacy entries recorded before per-strategy tagging existed) — this is
    what the combined dashboard trade history wants. With `strategy` set,
    returns only tickets tagged as opened by that strategy; legacy
    untagged entries are excluded since which strategy opened them is
    unknown.
    """
    with _LOCK:
        raw = _load_raw()
        if strategy is None:
            return {int(t) for t in raw.keys()}
        return {
            int(t) for t, entry in raw.items()
            if isinstance(entry, dict) and entry.get("strategy") == strategy
        }


def _entry_ts(entry) -> str:
    if isinstance(entry, dict):
        return entry.get("ts", "")
    return entry  # legacy format: plain ISO-timestamp string


def _safe_parse(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None
