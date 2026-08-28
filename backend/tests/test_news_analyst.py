"""Storage, grading, and live entry filter for the News Analyst.

The Claude call itself is not exercised here — what can silently go wrong
in live is the on-disk history: a leftover US30 row crashing the new
per-symbol layout, or yesterday's DE30 call being graded against USTEC's
price.
"""
from dataclasses import asdict

import pytest

import news_analyst
from news_analyst import BiasCall


def _call(**overrides) -> BiasCall:
    base = dict(
        date="2026-08-20",
        symbol="DE30m",
        direction="bullish",
        confidence=0.7,
        reasoning="ECB hold",
        key_factors=["ECB"],
        reference_price=24000.0,
        model="test",
        created_at="2026-08-20T12:00:00+00:00",
    )
    base.update(overrides)
    return BiasCall(**base)


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(news_analyst, "_store_path", lambda: tmp_path / "news_bias_history.json")


class TestRecordAndLoad:
    def test_stores_per_symbol_under_the_date(self):
        news_analyst.record_bias(_call(symbol="DE30m"))
        news_analyst.record_bias(_call(symbol="USTECm", reference_price=20000.0))
        history = news_analyst.load_bias_history()
        assert [c["symbol"] for c in history] == ["DE30m", "USTECm"]

    def test_has_called_today_requires_every_live_symbol(self):
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m"))
        assert news_analyst.has_called_today("2026-08-21", ["DE30m"])
        assert not news_analyst.has_called_today("2026-08-21", ["DE30m", "USTECm"])

    def test_legacy_us30_row_is_not_treated_as_a_live_book_call(self):
        legacy = asdict(_call(symbol="US30"))
        del legacy["symbol"]
        news_analyst._save_all({"2026-08-21": legacy})
        assert news_analyst.has_called_today("2026-08-21") is False
        assert news_analyst.load_bias_history() == []


class TestGradePending:
    def test_grades_each_symbol_against_its_own_price(self):
        news_analyst.record_bias(_call(symbol="DE30m", direction="bullish", reference_price=24000.0))
        news_analyst.record_bias(_call(symbol="USTECm", direction="bearish", reference_price=20000.0))
        graded = news_analyst.grade_pending_calls(
            {"DE30m": 24100.0, "USTECm": 19900.0},
            current_date="2026-08-21",
        )
        by_symbol = {g.symbol: g for g in graded}
        assert by_symbol["DE30m"].actual_direction == "bullish"
        assert by_symbol["DE30m"].graded is True
        assert by_symbol["USTECm"].actual_direction == "bearish"
        assert by_symbol["USTECm"].graded is True

    def test_does_not_grade_today_or_already_graded_calls(self):
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m"))
        news_analyst.record_bias(_call(
            date="2026-08-19", symbol="DE30m", graded=True, actual_direction="bullish",
        ))
        assert news_analyst.grade_pending_calls({"DE30m": 24100.0}, "2026-08-21") == []

    def test_skips_a_symbol_with_no_current_price(self):
        news_analyst.record_bias(_call(symbol="DE30m"))
        news_analyst.record_bias(_call(symbol="USTECm", reference_price=20000.0))
        graded = news_analyst.grade_pending_calls({"DE30m": 23900.0}, "2026-08-21")
        assert [g.symbol for g in graded] == ["DE30m"]
        assert graded[0].graded is False

    def test_legacy_us30_row_is_left_ungraded(self):
        legacy = asdict(_call(symbol="US30"))
        del legacy["symbol"]
        news_analyst._save_all({"2026-08-20": legacy})
        assert news_analyst.grade_pending_calls({"US30": 40000.0, "DE30m": 24000.0}, "2026-08-21") == []


class TestEntryFilter:
    def test_opposite_bias_is_rejected(self, monkeypatch):
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_ENABLED", True)
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_FILTER", True)
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m", direction="bearish"))
        assert news_analyst.reject_entry("DE30m", "long", "2026-08-21")
        assert news_analyst.reject_entry("DE30m", "short", "2026-08-21") is None

    def test_matching_bias_is_allowed(self, monkeypatch):
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_ENABLED", True)
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_FILTER", True)
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m", direction="bullish"))
        assert news_analyst.reject_entry("DE30m", "long", "2026-08-21") is None
        assert news_analyst.reject_entry("DE30m", "short", "2026-08-21")

    def test_neutral_or_missing_call_does_not_block(self, monkeypatch):
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_ENABLED", True)
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_FILTER", True)
        assert news_analyst.reject_entry("DE30m", "long", "2026-08-21") is None
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m", direction="neutral"))
        assert news_analyst.reject_entry("DE30m", "short", "2026-08-21") is None

    def test_filter_off_never_blocks(self, monkeypatch):
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_ENABLED", True)
        monkeypatch.setattr(news_analyst.config, "NEWS_ANALYST_FILTER", False)
        news_analyst.record_bias(_call(date="2026-08-21", symbol="DE30m", direction="bearish"))
        assert news_analyst.reject_entry("DE30m", "long", "2026-08-21") is None
    def test_matches_broker_suffix(self):
        prices = {"DE30m": 1.0, "USDJPYm": 2.0}
        assert news_analyst._match_symbol("DE30m", prices) == "DE30m"
        assert news_analyst._match_symbol("DE30", prices) == "DE30m"
        assert news_analyst._match_symbol("usdjpy", prices) == "USDJPYm"
        assert news_analyst._match_symbol("XAUUSD", prices) is None
