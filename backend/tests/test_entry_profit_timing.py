from types import SimpleNamespace

import pandas as pd

from backtests.entry_profit_timing import first_profit_timing


def _frame(closes):
    return pd.DataFrame(
        {
            "timestamp_ny": pd.date_range(
                "2026-01-01 09:00", periods=len(closes), freq="1h", tz="America/New_York"
            ),
            "close": closes,
        }
    )


def _trade(frame, *, pnl=-10.0, exit_offset=2):
    return SimpleNamespace(
        entry_time=frame["timestamp_ny"].iloc[0],
        exit_time=frame["timestamp_ny"].iloc[exit_offset],
        direction="long",
        entry_price=100.0,
        units=1.0,
        tp1_exit_time=None,
        tp1_exit_price=None,
        pnl_dollars=pnl,
    )


def test_first_profit_uses_commission_adjusted_completed_close():
    frame = _frame([103.0, 106.0, 95.0])

    result = first_profit_timing(_trade(frame), frame, commission=5.0)

    assert result.ever_profitable is True
    assert result.bars_to_profit == 2
    assert result.minutes_to_profit == 120.0
    assert result.first_profit_source == "bar_close"


def test_profitable_booked_exit_counts_when_no_prior_close_does():
    frame = _frame([99.0, 99.0])
    trade = _trade(frame, pnl=25.0, exit_offset=1)

    result = first_profit_timing(trade, frame, commission=5.0)

    assert result.ever_profitable is True
    assert result.bars_to_profit == 2
    assert result.first_profit_source == "profitable_exit"


def test_trade_can_close_without_ever_showing_profit():
    frame = _frame([99.0, 98.0, 95.0])

    result = first_profit_timing(_trade(frame), frame, commission=5.0)

    assert result.ever_profitable is False
    assert result.bars_to_profit is None
    assert result.bars_observed == 3
