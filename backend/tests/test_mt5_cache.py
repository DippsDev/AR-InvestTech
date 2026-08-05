"""Tests for the per-loop-tick MT5 snapshot (src/mt5_cache.py).

The cache exists to stop nine adapters asking MT5 the same question nine times
per loop tick. What matters is that it collapses those reads *and* that it
never serves a stale answer where the adapter needs a fresh one — a stale
position snapshot in the trailing-stop path would move a stop against a price
that has already gone.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src import mt5_cache

NY_TZ = ZoneInfo("America/New_York")


class FakeMT5:
    """Counts calls so a test can assert how many round-trips actually happened."""

    def __init__(self, account=None, positions=(), deals=(), tick=None, info=None):
        self._account = account
        # None is preserved, not coerced: MT5 returns it when the terminal is
        # busy and the cache is expected to cope with that.
        self._positions = positions if positions is None else tuple(positions)
        self._deals = deals if deals is None else tuple(deals)
        self._tick = tick
        self._info = info
        self.calls = {
            "account_info": 0,
            "positions_get": 0,
            "history_deals_get": 0,
            "symbol_info": 0,
            "symbol_info_tick": 0,
        }

    def account_info(self):
        self.calls["account_info"] += 1
        return self._account

    def positions_get(self, **kwargs):
        self.calls["positions_get"] += 1
        return self._positions

    def history_deals_get(self, from_date, to_date):
        self.calls["history_deals_get"] += 1
        self.last_window = (from_date, to_date)
        return self._deals

    def symbol_info(self, symbol):
        self.calls["symbol_info"] += 1
        return self._info

    def symbol_info_tick(self, symbol):
        self.calls["symbol_info_tick"] += 1
        return self._tick


@pytest.fixture
def fake(monkeypatch):
    """Install a counting fake in place of the real MT5 module."""
    stub = FakeMT5(
        account=SimpleNamespace(balance=1000.0, equity=980.0),
        positions=(
            SimpleNamespace(ticket=111, sl=1.0, profit=5.0),
            SimpleNamespace(ticket=222, sl=2.0, profit=-3.0),
        ),
        deals=(SimpleNamespace(ticket=1),),
        tick=SimpleNamespace(time=int(datetime.now(timezone.utc).timestamp()), bid=1.0, ask=1.1),
        info=SimpleNamespace(digits=5, volume_min=0.01),
    )
    monkeypatch.setattr(mt5_cache, "mt5", stub)
    mt5_cache.begin_tick()
    yield stub
    mt5_cache.begin_tick()


class TestDeduplication:
    def test_account_info_hits_mt5_once_per_tick(self, fake):
        results = [mt5_cache.account_info() for _ in range(9)]
        assert fake.calls["account_info"] == 1
        assert all(r is results[0] for r in results)

    def test_deals_are_fetched_once_for_all_three_strategies(self, fake):
        for _ in range(9):
            mt5_cache.history_deals_today(timedelta(0), NY_TZ)
        assert fake.calls["history_deals_get"] == 1

    def test_symbol_reads_are_per_symbol_not_per_caller(self, fake):
        for symbol in ("DE30m", "EURUSDm", "DE30m", "EURUSDm", "DE30m"):
            mt5_cache.symbol_info(symbol)
            mt5_cache.symbol_info_tick(symbol)
        assert fake.calls["symbol_info"] == 2
        assert fake.calls["symbol_info_tick"] == 2

    def test_positions_get_filters_the_snapshot_instead_of_requerying(self, fake):
        # Four reads keyed by ticket — what one cycle does per open position
        # across sync, status logging, breakeven and trail.
        for _ in range(4):
            assert [p.ticket for p in mt5_cache.positions_get(ticket=111)] == [111]
        assert fake.calls["positions_get"] == 1

    def test_unknown_ticket_returns_empty_not_none(self, fake):
        assert mt5_cache.positions_get(ticket=999) == []

    def test_none_result_is_remembered_rather_than_retried(self, monkeypatch):
        # MT5 returns None when the terminal is busy. Without a sentinel every
        # adapter after the first would retry the call that just failed.
        stub = FakeMT5(account=None, tick=None, info=None)
        monkeypatch.setattr(mt5_cache, "mt5", stub)
        mt5_cache.begin_tick()

        for _ in range(9):
            assert mt5_cache.account_info() is None
            assert mt5_cache.symbol_info_tick("DE30m") is None
        assert stub.calls["account_info"] == 1
        assert stub.calls["symbol_info_tick"] == 1


class TestFreshness:
    def test_begin_tick_drops_the_previous_snapshot(self, fake):
        mt5_cache.account_info()
        mt5_cache.positions_get()
        mt5_cache.symbol_info_tick("DE30m")

        mt5_cache.begin_tick()

        mt5_cache.account_info()
        mt5_cache.positions_get()
        mt5_cache.symbol_info_tick("DE30m")
        assert fake.calls["account_info"] == 2
        assert fake.calls["positions_get"] == 2
        assert fake.calls["symbol_info_tick"] == 2

    def test_invalidate_positions_forces_a_refetch(self, fake):
        # This is what protects the trailing stop: after breakeven moves the SL,
        # the trail phase must read the new SL, not the pre-move snapshot.
        mt5_cache.positions_get(ticket=111)
        mt5_cache.invalidate_positions()
        mt5_cache.positions_get(ticket=111)
        assert fake.calls["positions_get"] == 2

    def test_invalidate_positions_leaves_other_facts_cached(self, fake):
        mt5_cache.account_info()
        mt5_cache.invalidate_positions()
        mt5_cache.account_info()
        assert fake.calls["account_info"] == 1


class TestDealsWindow:
    def test_window_starts_at_ny_midnight_in_broker_clock(self, fake):
        offset = timedelta(hours=3)
        mt5_cache.history_deals_today(offset, NY_TZ)
        from_date, to_date = fake.last_window

        expected_start = (
            datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc) + offset
        )
        assert abs((from_date - expected_start).total_seconds()) < 1
        assert from_date < to_date

    def test_returns_a_list_even_when_mt5_returns_none(self, monkeypatch):
        stub = FakeMT5(deals=None)
        monkeypatch.setattr(mt5_cache, "mt5", stub)
        mt5_cache.begin_tick()
        assert mt5_cache.history_deals_today(timedelta(0), NY_TZ) == []

    def test_callers_cannot_mutate_the_shared_snapshot(self, fake):
        first = mt5_cache.history_deals_today(timedelta(0), NY_TZ)
        first.clear()
        assert len(mt5_cache.history_deals_today(timedelta(0), NY_TZ)) == 1


class TestStats:
    def test_counts_round_trips_against_snapshot_hits(self, fake):
        mt5_cache.begin_tick()
        for _ in range(9):
            mt5_cache.account_info()
        fetches, hits = mt5_cache.tick_stats()
        assert (fetches, hits) == (1, 8)
