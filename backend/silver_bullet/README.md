# Silver Bullet — Backtest Engine

An automated backtest of the ICT "Silver Bullet" intraday strategy on US30 (or any
index CFD) using 5-minute OHLCV data.

> **Educational use only.** This mechanises a discretionary method; nothing here
> implies profitability.  Run a full backtest with realistic costs before drawing
> any conclusions.

---

## Quick start

```bash
# 1. Install dependencies (first time only)
pip install pandas numpy pytest zoneinfo   # zoneinfo is stdlib in Python 3.9+

# 2. Generate sample data (skip if you have real data)
python -m silver_bullet.generate_sample_data --out us30_m5_sample.csv

# 3. Run backtest
python -m silver_bullet.run_backtest --data us30_m5.csv

# 4. Save trade log to CSV
python -m silver_bullet.run_backtest --data us30_m5.csv --export-trades trades.csv

# 5. Run unit tests
python -m pytest silver_bullet/tests/ -v
```

---

## CSV format

One row per completed 5-minute candle, UTC timestamps:

```
timestamp_utc,open,high,low,close,volume
2024-01-02 15:00:00+00:00,37000.0,37050.2,36990.1,37030.5,312
2024-01-02 15:05:00+00:00,37030.5,37080.0,37020.3,37060.1,287
...
```

Column names must match exactly.  Any ISO-8601 UTC string is accepted in
`timestamp_utc`.

---

## Strategy overview

**Session windows (America/New_York, DST-aware)**
Default: 10:00–11:00 and 11:00–12:00.  One independent setup allowed per window.

**Liquidity & sweeps**
- A *swing high/low* is confirmed when `swing_lookback` bars on both sides are
  lower/higher than the pivot (no lookahead — the pivot must be fully surrounded
  by closed bars before it is eligible for sweeping).
- *Sellside sweep* (bullish bias): a bar's low pierces below a recent swing low
  **and** closes back above it (wick, not breakout).
- *Buyside sweep* (bearish bias): a bar's high pierces above a recent swing high
  **and** closes back below it.

**Fair Value Gap (FVG)**
3-candle imbalance on the 5-minute chart, minimum `fvg_min_points` wide:

| Type     | Condition             | Zone                     |
|----------|-----------------------|--------------------------|
| Bullish  | low[3] > high[1]      | (high[1], low[3])        |
| Bearish  | high[3] < low[1]      | (high[3], low[1])        |

*[1] = oldest, [3] = newest of the three candles.*

**Direction logic**

| Sweep       | Bias     | FVG type | Trade |
|-------------|----------|----------|-------|
| Sellside    | Bullish  | Bullish  | Long  |
| Buyside     | Bearish  | Bearish  | Short |

**Entry / stop / target**
- Entry: limit order at the FVG's `entry_in_fvg` edge (default `near_edge`).
- Stop: swept extreme ± `stop_buffer_points`.
- Target: fixed `rr` × risk (default 3.0) **or** nearest opposite liquidity pool.
- Degenerate setups where risk < `min_risk_points` are skipped entirely.

---

## All CLI options

```
python -m silver_bullet.run_backtest \
  --data          us30_m5.csv          # required: M5 OHLCV CSV
  --symbol        US30
  --windows       "10:00-11:00,11:00-12:00"   # comma-separated NY windows
  --swing-lookback   3                 # bars on each side to confirm swing
  --sweep-lookback  20                 # bars to scan for sweep-eligible swings
  --fvg-min-points   5.0              # minimum FVG width in points
  --entry-in-fvg  near_edge           # near_edge | mid | far_edge
  --stop-buffer      3.0              # extra points beyond sweep extreme
  --target-mode   rr                  # rr | opposite_liquidity
  --rr               3.0
  --min-risk         5.0              # skip setups with <N points of risk
  --spread           2.0              # full spread in points
  --commission       5.0              # USD per round-trip
  --slippage         1.0              # additional slippage per fill in points
  --risk           100.0              # USD risked per trade (for position sizing)
  --point-value      1.0              # USD per index point per unit
  --export-trades trades.csv          # optional: save full trade log
  --show-trades     10                # print first N trades to console
```

---

## Configuring in code

All parameters live in `SilverBulletConfig` ([silver_bullet/config.py](config.py)).
Override any field:

```python
from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics, print_metrics

cfg = SilverBulletConfig(
    swing_lookback=5,
    rr=2.5,
    target_mode="opposite_liquidity",
    risk_per_trade=200.0,
)

df = prepare("us30_m5.csv", cfg)
trades = run_backtest(df, cfg)
print_metrics(compute_metrics(trades))
```

---

## Module layout

```
silver_bullet/
  config.py           All tunables (dataclass)
  data.py             CSV loading, UTC→NY, window flags
  indicators.py       Pure functions: swing, sweep, FVG, liquidity
  strategy.py         Signal generation (decoupled from execution)
  backtest.py         Event loop, fills, costs, trade ledger
  metrics.py          Performance statistics
  run_backtest.py     CLI entry point
  generate_sample_data.py  Synthetic data for smoke-testing
  tests/
    test_indicators.py  33 unit tests for all detector functions
```

**No-lookahead guarantee**: a swing at bar *j* is only visible to the strategy
at bar *j + swing_lookback*.  `detect_sellside_sweep` and `detect_buyside_sweep`
enforce this by scanning only up to `current_bar − swing_lookback − 1`.

---

## Metrics output

| Metric           | Description                                      |
|------------------|--------------------------------------------------|
| `win_rate_pct`   | % of trades that hit the take-profit target      |
| `avg_r`          | Mean R-multiple across all closed trades         |
| `expectancy_usd` | Average P/L per trade in USD                     |
| `profit_factor`  | Gross profit / gross loss                        |
| `max_drawdown_usd` | Largest peak-to-trough on the equity curve     |
| `exit_breakdown` | Count of target / stop / time-exit outcomes      |

---

## Next steps (out of scope for this phase)

- Live broker adapter: strategy logic is in `strategy.py` (returns `Signal` objects);
  wire a broker adapter to consume those without touching strategy code.
- M1 entry refinement: `prepare()` accepts an optional `--m1` CSV; hook it into
  `strategy.py` for tighter entry timing.
- Parameter optimisation: iterate over `SilverBulletConfig` fields, re-run
  `run_backtest`, compare `compute_metrics` — no code changes required.
- Walk-forward validation: split data into in-sample / out-of-sample windows.
