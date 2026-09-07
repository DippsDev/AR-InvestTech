"""Tests for shared daily circuit-breaker evaluation."""
from __future__ import annotations

import sys
from datetime import timedelta
from types import ModuleType, SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

# MetaTrader5 is Windows-only; stub the constants the helper imports.
if "MetaTrader5" not in sys.modules:
    _mt5 = ModuleType("MetaTrader5")
    _mt5.DEAL_TYPE_BUY = 0
    _mt5.DEAL_TYPE_SELL = 1
    _mt5.DEAL_ENTRY_IN = 0
    sys.modules["MetaTrader5"] = _mt5

import MetaTrader5 as mt5  # noqa: E402

from src import daily_limits, mt5_cache, ticket_store  # noqa: E402

NY_TZ = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _reset_session():
    daily_limits.reset_session_entries("__test__")
    daily_limits._SESSION_ENTRIES = 0  # noqa: SLF001
    daily_limits._SESSION_DATE = ""  # noqa: SLF001
    yield
    daily_limits._SESSION_ENTRIES = 0  # noqa: SLF001
    daily_limits._SESSION_DATE = ""  # noqa: SLF001


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "bot_tickets.json"
    monkeypatch.setattr(ticket_store, "_store_path", lambda: path)
    monkeypatch.setattr(ticket_store, "_cache", None, raising=False)
    monkeypatch.setattr(ticket_store, "_cache_stamp", None, raising=False)
    return path


def _deal(**kwargs):
    defaults = dict(
        symbol="DE30m",
        magic=202411001,
        position_id=1001,
        type=mt5.DEAL_TYPE_BUY,
        entry=mt5.DEAL_ENTRY_IN,
        profit=0.0,
        commission=0.0,
        swap=0.0,
        comment="Trendline_MKT",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _pos(**kwargs):
    defaults = dict(
        symbol="DE30m",
        magic=202411001,
        ticket=1001,
        comment="Trendline_MKT",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestEvaluateDailyLimits:
    def test_fail_closed_when_history_raises(self, store, monkeypatch):
        def boom(*_a, **_k):
            raise RuntimeError("mt5 down")

        monkeypatch.setattr(mt5_cache, "history_deals_today", boom)
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [])

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is False
        assert verdict.reason == "history_unavailable"

    def test_open_positions_floor_blocks_stacking(self, store, monkeypatch):
        monkeypatch.setattr(mt5_cache, "history_deals_today", lambda *_a, **_k: [])
        monkeypatch.setattr(
            mt5_cache,
            "positions_get",
            lambda: [_pos(ticket=i) for i in range(1, 7)],
        )

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is False
        assert verdict.reason == "trade_cap"
        assert verdict.open_owned == 6
        assert verdict.daily_entries == 6

    def test_counts_across_symbols_and_strategies(self, store, monkeypatch):
        monkeypatch.setattr(
            mt5_cache,
            "history_deals_today",
            lambda *_a, **_k: [
                _deal(symbol="DE30m", magic=202411001, position_id=1),
                _deal(symbol="USDJPYm", magic=202406122, position_id=2,
                      comment="SilverBullet_MKT"),
                _deal(symbol="USTECm", magic=202507001, position_id=3,
                      comment="Mutanabby_MKT"),
            ],
        )
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [])

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is True
        assert verdict.daily_entries == 3

        verdict_capped = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=3,
            loss_limit_usd=10.0,
        )
        assert verdict_capped.allowed is False
        assert verdict_capped.reason == "trade_cap"

    def test_comment_attribution_when_magic_wiped(self, store, monkeypatch):
        monkeypatch.setattr(
            mt5_cache,
            "history_deals_today",
            lambda *_a, **_k: [
                _deal(magic=0, position_id=55, comment="Trendline_MKT_TP1"),
                _deal(magic=0, position_id=56, comment="Trendline_MKT_TP2"),
            ],
        )
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [])

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is True
        assert verdict.daily_entries == 2

    def test_session_floor_blocks_even_if_history_empty(self, store, monkeypatch):
        monkeypatch.setattr(mt5_cache, "history_deals_today", lambda *_a, **_k: [])
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [])
        daily_limits.note_entry_placed(5, ny_date="2026-09-07")

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is False
        assert verdict.reason == "trade_cap"

    def test_under_cap_allows_entry(self, store, monkeypatch):
        monkeypatch.setattr(
            mt5_cache,
            "history_deals_today",
            lambda *_a, **_k: [_deal(position_id=1)],
        )
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [_pos(ticket=1)])

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
            session_entries=1,
        )
        assert verdict.allowed is True
        assert verdict.daily_entries == 1

    def test_daily_loss_limit_account_wide(self, store, monkeypatch):
        monkeypatch.setattr(
            mt5_cache,
            "history_deals_today",
            lambda *_a, **_k: [
                _deal(profit=-6.0, entry=1),  # exit deal
                _deal(magic=202406122, position_id=2, profit=-5.0, entry=1,
                      comment="SilverBullet_MKT"),
            ],
        )
        monkeypatch.setattr(mt5_cache, "positions_get", lambda: [])

        verdict = daily_limits.evaluate_daily_limits(
            broker_utc_offset=timedelta(0),
            ny_tz=NY_TZ,
            max_trades=5,
            loss_limit_usd=10.0,
        )
        assert verdict.allowed is False
        assert verdict.reason == "loss_limit"
