from datetime import date, timedelta

import numpy as np
import pandas as pd

from backtests.mutanabby_survival_exit import split_dates
from mutanabby.backtest import BacktestCosts, run_backtest
from mutanabby.config import MutanabbyConfig


def _trending_frame(n: int = 600, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = np.cumsum(rng.normal(1.0, 25.0, n)) + 43_000.0
    high = close + rng.uniform(5.0, 25.0, n)
    low = close - rng.uniform(5.0, 25.0, n)
    opens = np.concatenate([[close[0]], close[:-1]])
    timestamps = pd.date_range(
        "2025-01-06 09:30", periods=n, freq="5min", tz="America/New_York"
    )
    return pd.DataFrame(
        {
            "timestamp_ny": timestamps,
            "open": opens,
            "high": high,
            "low": low,
            "close": close,
            "date_str": [str(timestamp.date()) for timestamp in timestamps],
            "is_news_day": False,
        }
    )


class _ExitImmediately:
    def __init__(self) -> None:
        self.calls: list[tuple[pd.Timestamp, int]] = []

    def should_exit(self, trade, decision_bar_idx: int) -> bool:
        self.calls.append((trade.entry_time, decision_bar_idx))
        return True


def test_dynamic_exit_uses_completed_bar_and_fills_next_open() -> None:
    frame = _trending_frame()
    policy = _ExitImmediately()
    costs = BacktestCosts(
        spread_points=0.0,
        slippage_points=0.0,
        commission_per_trade=0.0,
    )

    trades = run_backtest(frame, MutanabbyConfig(), costs, exit_policy=policy)

    survival_exits = [trade for trade in trades if trade.exit_reason == "survival_exit"]
    assert survival_exits
    first = survival_exits[0]
    exit_idx = frame.index[frame["timestamp_ny"] == first.exit_time].item()
    assert first.exit_time > first.entry_time
    assert first.exit_price == frame.loc[exit_idx, "open"]
    assert (first.entry_time, exit_idx - 1) in policy.calls


def test_split_dates_is_chronological_and_disjoint() -> None:
    dates = [date(2025, 1, 1) + timedelta(days=offset) for offset in range(100)]

    model, validation, test = split_dates(dates, 0.30, 0.70)

    assert len(model) == 49
    assert len(validation) == 21
    assert len(test) == 30
    assert model[-1] < validation[0] < test[0]
    assert not (set(model) & set(validation))
    assert not (set(model) & set(test))
    assert not (set(validation) & set(test))
