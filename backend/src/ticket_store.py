"""Local record of MT5 position tickets this bot has opened.

Some brokers (seen on AtlasFunded-Server) zero out the `magic` field on
deals regardless of what was set on the order, which breaks matching this
bot's trades against MT5 history by magic number alone. This module gives
callers a broker-independent fallback: every ticket the bot itself confirms
opening is recorded here (tagged with which strategy opened it), and
history lookups can match against that set instead of (or in addition to)
magic. `load_tickets(strategy=...)` lets Silver Bullet's, Trendline's and
Mutanabby's own daily circuit breakers each see only their own tickets even
when magic is unreliable; `load_tickets()` with no filter (used by the dashboard's
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

# Parsed store, memoised against the file's (mtime_ns, size). Every adapter's
# daily circuit breaker calls load_tickets() on every cycle, which meant nine
# reads and nine JSON parses of the same small file every 5 seconds. The file
# only changes when record_ticket() writes it — a few times a day — so the
# stat() is enough to know the parse can be reused.
_cache: dict | None = None
_cache_stamp: tuple[int, int] | None = None


def _store_path():
    return paths.app_data_dir() / "bot_tickets.json"


def _file_stamp(path) -> tuple[int, int] | None:
    """(mtime_ns, size) identifying this version of the file, or None if absent."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _load_raw() -> dict:
    """Parsed store contents, reusing the last parse when the file is unchanged.

    Caller must hold _LOCK — the cache globals are not separately guarded.
    """
    global _cache, _cache_stamp

    path = _store_path()
    stamp = _file_stamp(path)
    if stamp is None:
        _cache, _cache_stamp = None, None
        return {}

    if _cache is not None and _cache_stamp == stamp:
        return _cache

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _cache, _cache_stamp = None, None
        return {}

    # Re-stat after reading: if the file changed while we were reading it, the
    # parse may be of a torn write, so use it once but don't memoise it.
    _cache = data
    _cache_stamp = stamp if _file_stamp(path) == stamp else None
    return data


def record_ticket(ticket: int, strategy: str | None = None) -> None:
    """Record that the bot opened `ticket`, optionally tagged with which
    strategy ("SB", "TL" or "MB") opened it. Safe to call from any thread."""
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

        path = _store_path()
        path.write_text(json.dumps(data), encoding="utf-8")

        # Adopt what we just wrote as the cached parse, so the nine readers
        # that follow don't each re-read and re-parse the file we already hold.
        global _cache, _cache_stamp
        _cache = data
        _cache_stamp = _file_stamp(path)


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
