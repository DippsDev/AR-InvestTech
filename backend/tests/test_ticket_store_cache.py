"""Tests for the memoised read in src/ticket_store.

Every adapter's daily circuit breaker calls load_tickets() each cycle, so the
store was being read and JSON-parsed nine times every five seconds. Caching it
is only safe if a write is still observed immediately — a stale ticket set
would let a strategy's daily trade cap be undercounted.
"""
import json

import pytest

from src import ticket_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the store at a temp file and clear the memoised parse."""
    path = tmp_path / "bot_tickets.json"
    monkeypatch.setattr(ticket_store, "_store_path", lambda: path)
    monkeypatch.setattr(ticket_store, "_cache", None, raising=False)
    monkeypatch.setattr(ticket_store, "_cache_stamp", None, raising=False)
    return path


class TestCorrectness:
    def test_missing_file_reads_as_empty(self, store):
        assert ticket_store.load_tickets() == set()
        assert ticket_store.load_tickets(strategy="SB") == set()

    def test_recorded_ticket_is_visible_immediately(self, store):
        ticket_store.record_ticket(111, strategy="SB")
        assert ticket_store.load_tickets(strategy="SB") == {111}

    def test_second_write_is_visible_immediately(self, store):
        # The dangerous case: a cached parse from before the write.
        ticket_store.record_ticket(111, strategy="SB")
        ticket_store.load_tickets(strategy="SB")
        ticket_store.record_ticket(222, strategy="SB")
        assert ticket_store.load_tickets(strategy="SB") == {111, 222}

    def test_strategies_stay_isolated(self, store):
        ticket_store.record_ticket(111, strategy="SB")
        ticket_store.record_ticket(222, strategy="TL")
        ticket_store.record_ticket(333, strategy="MB")
        assert ticket_store.load_tickets(strategy="SB") == {111}
        assert ticket_store.load_tickets(strategy="TL") == {222}
        assert ticket_store.load_tickets(strategy="MB") == {333}
        assert ticket_store.load_tickets() == {111, 222, 333}

    def test_an_external_write_is_picked_up(self, store):
        ticket_store.record_ticket(111, strategy="SB")
        assert ticket_store.load_tickets(strategy="SB") == {111}

        # Another process (the dashboard, a restarted bot) rewrites the file.
        store.write_text(
            json.dumps({"999": {"ts": "2026-01-01T00:00:00+00:00", "strategy": "SB"}}),
            encoding="utf-8",
        )
        assert ticket_store.load_tickets(strategy="SB") == {999}

    def test_corrupt_file_reads_as_empty_and_does_not_poison_the_cache(self, store):
        store.write_text("{not json", encoding="utf-8")
        assert ticket_store.load_tickets() == set()

        ticket_store.record_ticket(111, strategy="SB")
        assert ticket_store.load_tickets(strategy="SB") == {111}


class TestCaching:
    def test_repeated_reads_parse_the_file_once(self, store, monkeypatch):
        ticket_store.record_ticket(111, strategy="SB")

        parses = {"n": 0}
        real_loads = json.loads

        def counting_loads(*args, **kwargs):
            parses["n"] += 1
            return real_loads(*args, **kwargs)

        monkeypatch.setattr(ticket_store.json, "loads", counting_loads)

        # Nine adapters, three cycles each.
        for _ in range(27):
            ticket_store.load_tickets(strategy="SB")
        assert parses["n"] == 0, "cached parse should serve every read"

    def test_deleting_the_file_clears_the_cache(self, store):
        ticket_store.record_ticket(111, strategy="SB")
        assert ticket_store.load_tickets(strategy="SB") == {111}
        store.unlink()
        assert ticket_store.load_tickets(strategy="SB") == set()
