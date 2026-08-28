"""
News Analyst — shadow-mode daily directional bias for the live book.

Once per NY trading day, asks Claude to search news relevant to whatever
symbols the bot is actually running (SB / TL / MB adapters) and return a
structured bullish/bearish/neutral call per instrument, with confidence
and reasoning.

Calls are persisted and graded against the next day's price. When
NEWS_ANALYST_FILTER is on (the default), live adapters refuse new entries
that fight that symbol's call for the day: bullish → longs only, bearish →
shorts only, neutral or no call yet → both sides still allowed. The filter
never sizes trades and never takes down the bot loop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import config
from src import paths

NY_TZ = ZoneInfo("America/New_York")

# Broker suffixes ("m") stripped in matching; labels are for the Claude prompt.
_SYMBOL_LABELS = {
    "DE30m":   "DE30 / DAX (Germany 40 equity index) — ECB, German/Eurozone data, European equities",
    "USTECm":  "USTEC / Nasdaq-100 — Fed, US tech earnings, US macro",
    "USDJPYm": "USDJPY — Fed vs BoJ, US/Japan yields, risk sentiment",
    "JP225m":  "JP225 / Nikkei 225 — BoJ, Japanese data, USDJPY correlation",
    "XAUUSDm": "XAUUSD / gold — real yields, USD, geopolitics, Fed",
    "EURUSDm": "EURUSD — ECB vs Fed, Eurozone and US data",
    "GBPUSDm": "GBPUSD — BoE vs Fed, UK and US data",
    "US30m":   "US30 / Dow Jones Industrial Average — Fed, US macro, Dow-component earnings",
}

_CALL_SCHEMA = {
    "type": "object",
    "properties": {
        "symbol":      {"type": "string"},
        "direction":   {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "confidence":  {"type": "number", "description": "0.0-1.0"},
        "reasoning":   {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["symbol", "direction", "confidence", "reasoning", "key_factors"],
    "additionalProperties": False,
}

_SCHEMA = {
    "type": "object",
    "properties": {
        "calls": {"type": "array", "items": _CALL_SCHEMA},
    },
    "required": ["calls"],
    "additionalProperties": False,
}


@dataclass
class BiasCall:
    date: str            # NY calendar date, "YYYY-MM-DD"
    symbol: str
    direction: str        # "bullish" | "bearish" | "neutral"
    confidence: float
    reasoning: str
    key_factors: list
    reference_price: float
    model: str
    created_at: str       # ISO UTC timestamp
    graded: Optional[bool] = None       # None until graded; then True/False
    actual_direction: Optional[str] = None


def _store_path():
    return paths.app_data_dir() / "news_bias_history.json"


def _load_all() -> dict:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict) -> None:
    _store_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _is_legacy_day(day: object) -> bool:
    """Pre-multi-symbol store wrote one US30 call as a flat BiasCall under the date."""
    return isinstance(day, dict) and "direction" in day and not _looks_like_symbol_map(day)


def _looks_like_symbol_map(day: dict) -> bool:
    if not day:
        return False
    first = next(iter(day.values()))
    return isinstance(first, dict) and "direction" in first


def _day_calls(day: object) -> dict[str, dict]:
    """Return {symbol: record} for a date entry, ignoring leftover US30 rows."""
    if not isinstance(day, dict) or _is_legacy_day(day):
        return {}
    return {sym: rec for sym, rec in day.items() if isinstance(rec, dict) and "direction" in rec}


def symbol_label(symbol: str) -> str:
    if symbol in _SYMBOL_LABELS:
        return _SYMBOL_LABELS[symbol]
    bare = symbol[:-1] if symbol.endswith("m") else symbol
    return _SYMBOL_LABELS.get(bare, f"{symbol} (live traded instrument)")


def _match_symbol(raw: str, wanted: dict[str, float]) -> Optional[str]:
    raw_u = raw.strip().upper()
    for symbol in wanted:
        if symbol.upper() == raw_u:
            return symbol
    raw_bare = raw_u.rstrip("M")
    for symbol in wanted:
        if symbol.upper().rstrip("M") == raw_bare:
            return symbol
    return None


def record_bias(call: BiasCall) -> None:
    data = _load_all()
    day = data.get(call.date)
    if _is_legacy_day(day):
        day = {}
    elif not isinstance(day, dict):
        day = {}
    day[call.symbol] = asdict(call)
    data[call.date] = day
    _save_all(data)


def load_bias_history() -> list[dict]:
    """Return all recorded per-symbol bias calls, oldest first."""
    data = _load_all()
    out = []
    for date_str in sorted(data.keys()):
        for symbol in sorted(_day_calls(data[date_str])):
            out.append(data[date_str][symbol])
    return out


def has_called_today(date_str: str, symbols: Optional[list[str]] = None) -> bool:
    day = _day_calls(_load_all().get(date_str))
    if not day:
        return False
    if not symbols:
        return True
    return all(s in day for s in symbols)


def get_daily_bias(prices: dict[str, float]) -> list[BiasCall]:
    """Call Claude once for a bias on every live symbol. Raises on failure —
    callers must catch and log, never let this take down the bot loop."""
    import anthropic

    if not prices:
        raise RuntimeError("No symbols/prices supplied for today's bias call")
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    today_ny = datetime.now(NY_TZ).strftime("%Y-%m-%d")
    book_lines = "\n".join(
        f"- {symbol}: {symbol_label(symbol)} (reference price {price})"
        for symbol, price in prices.items()
    )
    prompt = (
        f"Today is {today_ny} (America/New_York). The live trading book is:\n"
        f"{book_lines}\n\n"
        "Search for the most relevant news for today's session on EACH instrument. "
        "Cover central-bank policy/speeches (Fed, ECB, BoJ, BoE as relevant to that "
        "name), high-impact macro data (NFP, CPI, GDP, FOMC and the equivalent for "
        "DE/JP/UK), major earnings or index-component news, overnight futures/FX "
        "session moves, and geopolitics likely to move that market. Return one bias "
        "call per listed broker symbol, using the symbol string exactly as given "
        "(e.g. DE30m). Direction is for that instrument's own price today."
    )

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request (refusal)")

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise RuntimeError("No text block in response")

    parsed = json.loads(text_block.text)
    created_at = datetime.now(timezone.utc).isoformat()
    calls: list[BiasCall] = []
    seen: set[str] = set()

    for raw in parsed.get("calls") or []:
        symbol = _match_symbol(str(raw.get("symbol", "")), prices)
        if symbol is None or symbol in seen:
            continue
        seen.add(symbol)
        calls.append(BiasCall(
            date=today_ny,
            symbol=symbol,
            direction=raw["direction"],
            confidence=float(raw["confidence"]),
            reasoning=raw["reasoning"],
            key_factors=raw["key_factors"],
            reference_price=prices[symbol],
            model=response.model,
            created_at=created_at,
        ))

    if not calls:
        raise RuntimeError("Claude returned no usable bias calls for the live book")
    return calls


def grade_pending_calls(prices: dict[str, float], current_date: str) -> list[BiasCall]:
    """Grade any prior-day per-symbol call that hasn't been graded yet, using
    that symbol's price move from its reference_price to now.
    Returns the list of calls just graded (for logging)."""
    data = _load_all()
    newly_graded = []

    for date_str, day in data.items():
        if date_str == current_date:
            continue
        for symbol, record in _day_calls(day).items():
            if record.get("graded") is not None or symbol not in prices:
                continue
            delta = prices[symbol] - record["reference_price"]
            if abs(delta) < 1e-9:
                actual = "neutral"
            else:
                actual = "bullish" if delta > 0 else "bearish"
            record["actual_direction"] = actual
            record["graded"] = (actual == record["direction"])
            payload = {**record, "symbol": record.get("symbol") or symbol}
            newly_graded.append(BiasCall(**payload))

    if newly_graded:
        _save_all(data)

    return newly_graded


def todays_bias(symbol: str, date_str: Optional[str] = None) -> Optional[str]:
    """Today's stored direction for `symbol`, or None if there is no call yet."""
    day = date_str or datetime.now(NY_TZ).strftime("%Y-%m-%d")
    record = _day_calls(_load_all().get(day)).get(symbol)
    if not record:
        return None
    direction = record.get("direction")
    return direction if direction in ("bullish", "bearish", "neutral") else None


def reject_entry(symbol: str, side: str, date_str: Optional[str] = None) -> Optional[str]:
    """Reason string if today's bias forbids this entry, else None (allow).

    A missing call or a neutral call does not block — a slow or failed Claude
    round must not freeze the book. Only an explicit opposite bias rejects.
    """
    if not (config.NEWS_ANALYST_ENABLED and config.NEWS_ANALYST_FILTER):
        return None
    bias = todays_bias(symbol, date_str)
    if bias not in ("bullish", "bearish"):
        return None
    side = (side or "").lower()
    if side == "long" and bias == "bearish":
        return f"{symbol} LONG vs bearish bias"
    if side == "short" and bias == "bullish":
        return f"{symbol} SHORT vs bullish bias"
    return None
