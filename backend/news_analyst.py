"""
News Analyst — shadow-mode daily directional bias.

Once per NY trading day, asks Claude to search the day's US30/Dow Jones-
relevant news (Fed policy, macro data releases, Dow-component earnings,
overnight futures moves, geopolitical events) and return a structured
bullish/bearish/neutral call with a confidence score and reasoning.

This is SHADOW MODE ONLY: the call is logged and persisted for later
evaluation against what price actually did — it never gates, sizes, or
otherwise touches real trade decisions. See bot.py's daily hook and
grade_pending_calls() for the evaluation loop.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import config
from src import paths

_SCHEMA = {
    "type": "object",
    "properties": {
        "direction":   {"type": "string", "enum": ["bullish", "bearish", "neutral"]},
        "confidence":  {"type": "number", "description": "0.0-1.0"},
        "reasoning":   {"type": "string"},
        "key_factors": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["direction", "confidence", "reasoning", "key_factors"],
    "additionalProperties": False,
}


@dataclass
class BiasCall:
    date: str            # NY calendar date, "YYYY-MM-DD"
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


def record_bias(call: BiasCall) -> None:
    data = _load_all()
    data[call.date] = asdict(call)
    _save_all(data)


def load_bias_history() -> list[dict]:
    """Return all recorded bias calls, oldest first."""
    data = _load_all()
    return [data[d] for d in sorted(data.keys())]


def has_called_today(date_str: str) -> bool:
    return date_str in _load_all()


def get_daily_bias(reference_price: float, symbol: str = "US30 (Dow Jones Industrial Average)") -> BiasCall:
    """Call Claude once to get today's directional bias. Raises on failure —
    callers must catch and log, never let this take down the bot loop."""
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    today_ny = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    prompt = (
        f"Today is {today_ny}. Search for the most relevant news for today's "
        f"trading session on {symbol}: Federal Reserve policy/speeches, "
        f"high-impact US macro data releases (NFP, CPI, GDP, FOMC), earnings "
        f"from major Dow-30 component companies, overnight futures moves, and "
        f"any major geopolitical events likely to move US equities. Based on "
        f"what you find, give a directional bias for today's session."
    )

    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the request (refusal)")

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise RuntimeError("No text block in response")

    parsed = json.loads(text_block.text)

    return BiasCall(
        date=today_ny,
        direction=parsed["direction"],
        confidence=float(parsed["confidence"]),
        reasoning=parsed["reasoning"],
        key_factors=parsed["key_factors"],
        reference_price=reference_price,
        model=response.model,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def grade_pending_calls(current_price: float, current_date: str) -> list[BiasCall]:
    """Grade any prior-day call that hasn't been graded yet, using the price
    movement from that call's reference_price to now as the actual outcome.
    Returns the list of calls just graded (for logging)."""
    data = _load_all()
    newly_graded = []

    for date_str, record in data.items():
        if date_str == current_date or record.get("graded") is not None:
            continue

        delta = current_price - record["reference_price"]
        if abs(delta) < 1e-9:
            actual = "neutral"
        else:
            actual = "bullish" if delta > 0 else "bearish"

        record["actual_direction"] = actual
        record["graded"] = (actual == record["direction"])
        newly_graded.append(BiasCall(**record))

    if newly_graded:
        _save_all(data)

    return newly_graded
