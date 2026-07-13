"""Local record of MT5 position tickets this bot has opened.

Some brokers (seen on AtlasFunded-Server) zero out the `magic` field on
deals regardless of what was set on the order, which breaks matching this
bot's trades against MT5 history by magic number alone. This module gives
`get_trades()` a broker-independent fallback: every ticket the bot itself
confirms opening is recorded here, and history lookups can match against
that set instead of (or in addition to) magic.
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


def record_ticket(ticket: int) -> None:
    """Record that the bot opened `ticket`. Safe to call from any thread."""
    with _LOCK:
        data = _load_raw()
        data[str(ticket)] = datetime.now(timezone.utc).isoformat()

        cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
        data = {
            t: ts for t, ts in data.items()
            if _safe_parse(ts) is None or _safe_parse(ts) >= cutoff
        }

        _store_path().write_text(json.dumps(data), encoding="utf-8")


def load_tickets() -> set[int]:
    """Return the set of position tickets the bot has opened (any recorded time)."""
    with _LOCK:
        return {int(t) for t in _load_raw().keys()}


def _safe_parse(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None
