# Mutanabby "Ultimate Algo" — Python port & backtest

A faithful port of the Pine v5 indicator in
`backend/Tradingview Indicator Mutanabby_AI V7.txt`, wired into the same
backtest harness conventions as `silver_bullet/` and `trendline/`.

**Bottom line: do not trade this as shipped.** At the indicator's own settings
it loses money on every instrument and timeframe tested. One variant shows a
soft positive ridge; the evidence for it is weak. Details below.

---

## What the indicator actually is

Roughly six lines of logic under a large amount of cosmetics:

```
supertrend = SuperTrend(ATR 11, factor = sensitivity 4)
bull = crossover(close, supertrend)  and close >= SMA(13)
bear = crossunder(close, supertrend) and close <= SMA(13)
stop = signal bar low  - ATR(14) x 1     (long)
       signal bar high + ATR(14) x 1     (short)
tp   = (entry - stop) x N + entry        for N = 1, 2, 3
```

The rest — 61 tiers of RSI bar colouring, an SMA(21)/SMA(34) ribbon, the
"Strong Buy" label text — affects no signal.

## Quick start

```bash
# Indicator defaults, native M5
python -m mutanabby.run_backtest --data data/us30_m5_max.csv

# The only configuration with any supporting evidence
python -m mutanabby.run_backtest --data data/us30_m5_max.csv \
    --timeframe 1h --sensitivity 6 --rr 2

python -m mutanabby.run_backtest --help
```

`MutanabbyConfig()` with no arguments reproduces the chart exactly.

---

## Findings

### 1. The SMA(13) "confirmation" filter is inert

The header advertises "SuperTrend + SMA confirmation". Measured over the stored
history, the SMA gate removes **2 of 940** US30 crossovers, **2 of 828** on
XAUUSD, and **0 of 894** on EURUSD.

This is structural, not a data quirk: a SuperTrend flip at sensitivity 4 needs
close to travel ~4x ATR, which all but guarantees it is already on the correct
side of a 13-bar mean. In practice this indicator is *just* SuperTrend.

### 2. M5 — the timeframe it is marketed for — is where it works worst

Config grid (rr x sensitivity) run across 6 instruments and 4 timeframes, with
each instrument's cost held **fixed across timeframes** (spread is a property of
the instrument, not the chart you view it on):

| Timeframe | Median PF | Profitable | Total trades | Net / symbol |
| --- | --- | --- | --- | --- |
| M5 (native) | 0.905 | 4 / 36 | 37,155 | −$36,391 |
| 15min | 0.875 | 6 / 36 | 11,839 | −$13,620 |
| **1h** | **1.005** | **17 / 34** | 2,547 | −$25 |
| 4h | 0.990 | 14 / 29 | 613 | +$723 |

At its own defaults on M5: US30 PF 0.93 (−$5,720 over 1,173 trades), XAUUSD
PF 0.82 (−$15,813 over 1,204 trades).

**Two separate effects, both real.** Re-running the same grid with all costs
zeroed isolates them:

| Timeframe | Median PF (costed) | Median PF (zero cost) |
| --- | --- | --- |
| M5 | 0.905 | 1.040 |
| 15min | 0.875 | 0.995 |
| 1h | 1.005 | **1.105** |
| 4h | 0.990 | 1.090 |

The raw signal *is* better on higher timeframes (1.105 vs 1.040) — but the
larger effect is that M5 fires 37,155 trades against H1's 2,547, so it pays
~15x the total spread to express the same idea. M5's signal is not worthless;
it just cannot carry its own execution cost.

Note what the first table does **not** say: H1's median PF of 1.005 is dead
breakeven. H1 is not good — M5 and 15min are bad. Only the narrow sensitivity
corner in the next section is meaningfully positive, and 4h is statistically
tied with H1 (better net, fewer trades).

### 3. The one configuration with support — and why it is not enough

`--timeframe 1h --sensitivity 6 --rr 2`, 1x ATR stop, no flip exit:

| Measure | Result |
| --- | --- |
| Profitable on | **10 / 12 instruments** |
| Median profit factor | 1.215 |
| Total net (12 symbols, $100 risk/trade) | +$6,715 |
| Trades | 692 total, ~56 per instrument |
| Worst instruments | ustecm PF 0.70, gbpusdm PF 0.74 |

Only US30 and XAUUSD were used to select these parameters, so the other **10
instruments are effectively out-of-sample — and 8 of those 10 are profitable**
(+$3,464). A 60/40 in-sample/out-of-sample split on H1 also held: 9 of the top
10 in-sample combos stayed profitable OOS.

Sweeping sensitivity with everything else fixed gives a broad ridge rather than
a lucky point — it peaks at 6.0 and stays at or above breakeven across the whole
5.0–7.0 range:

| sensitivity | 5.0 | 5.25 | 5.5 | 5.75 | **6.0** | 6.25 | 6.5 | 6.75 | 7.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| median PF | 1.005 | 1.015 | 1.140 | 1.095 | **1.215** | 1.125 | 1.090 | 1.035 | 1.015 |
| profitable | 6/12 | 6/12 | 8/12 | 8/12 | **10/12** | 8/12 | 9/12 | 7/12 | 6/12 |

That shape is the strongest evidence in this document. It is still not enough to
fund: the whole result rests on ~56 trades per instrument over 17 months, the
peak is only PF 1.2, and two instruments lose badly. Treat it as a hypothesis to
forward-test on demo, not a strategy to size up.

---

## Layout

| File | Role |
| --- | --- |
| `config.py` | Every tunable. Defaults reproduce the chart. |
| `indicators.py` | Pine ports: `supertrend`, `atr`, `rma`, `sma`, `rsi`, `crossover`. |
| `strategy.py` | `SignalGenerator` — bar-by-bar signals, no execution. |
| `backtest.py` | Event loop, fills, costs, trade management. |
| `data.py` | CSV load + optional resample to any timeframe. |
| `run_backtest.py` | CLI. |
| `live_adapter.py` | MT5 execution — H1 bars, market orders, risk caps. |
| `tests/` | 49 tests: parity pins on the Pine ports, plus live-wiring guards. |

---

## Running it live

Off by default. To enable:

```bash
MB_ENABLED=true
MB_RISK_PCT=0.25        # total across all MB instances, not per instance
```

Trades `US30m`, `JP225m`, `USDJPYm` on H1 at sensitivity 6 / rr 2
(`MB_TARGETS` in `multi_symbol_targets.py`). Symbols that don't resolve on the
broker are dropped at start-up rather than aborting the bot.

**MB has its own risk budget.** `bot.py` divides SB and TL risk by the SB+TL
instance count and MB risk by the MB instance count *separately*. Enabling MB
therefore leaves every Silver Bullet and Trendline position size untouched and
adds at most `MB_RISK_PCT` of new account exposure. This is deliberate — MB's
evidence is much weaker than theirs, so it must not fund itself out of their
budget. `tests/test_live_wiring.py` pins this.

Same safety rails as the other two adapters: drawdown circuit breaker
(`MB_MAX_DRAWDOWN_PCT`), daily loss limit (`MB_DAILY_LOSS_LIMIT_USD`), daily
trade cap (`MB_MAX_TRADES_PER_DAY`), news-day pause (`MB_NEWS`), small-account
sizing caps, and a 0.5R stale-signal guard matching the backtester's
`max_entry_slip_r`. Magic number `202507001`.

### Two adapter behaviours worth knowing

**It reads only the newest completed bar.** Trendline replays unprocessed bars
because its generator accumulates state; Mutanabby's precomputes everything, so
a rebuilt generator over the same window gives identical signals and replaying
older bars would only risk acting on stale ones. The forming bar is always
dropped — load-bearing here, since the source indicator's own header admits its
signals flicker until the close.

**`bars_lookback` must stay at or above 150.** The adapter rebuilds SuperTrend
from a rolling window rather than full history. SuperTrend is recursive, but its
band ratchet resets on every flip, so state converges: measured on 8,260 H1 US30
bars, a rolling window reproduces full-history signals with **0 mismatches at
≥150 bars**, and mismatches appear below ~100. The default 300 leaves 2× margin,
and the adapter refuses to trade on less.

**No adaptive daily-trade-floor boost.** Trendline widens tolerances late in the
day to clear `DAILY_TRADE_FLOOR`. Mutanabby has no equivalent knob — its only
entry parameter is `sensitivity`, and changing it recomputes the SuperTrend into
a *different* signal set rather than admitting marginal setups. That would
fabricate trades, which is what the boost is documented not to do.

### What was tried and rejected

Using this SuperTrend as a **regime filter on existing SB/TL entries** (keep a
trade only if its direction agrees with the H1 trend). Tested against the stored
SB/TL backtests: it improved 9 of 16 symbol files, median ΔPF **+0.041**, while
discarding 54% of trades and cutting total net from $13,721 to $7,451. A coin
flip that halves your sample — not worth wiring in.

## Porting notes

Details that look like bugs but are deliberate:

- **`supertrend_atr_length = 11`, not 14.** The Pine calls
  `supertrend(close, sensitivity, 11)` with a literal. Its user-facing
  "ATR Length" input (14) is shadowed by the function parameter of the same
  name and only ever reaches the SL/TP maths.
- **`prevSuperTrend == prevUpperBand` is exact float equality.** That is how
  TradingView's built-in remembers which side it is on; both values are the
  same float assigned on the previous bar. A tolerance changes the flips.
- **Band ratcheting reads the previous bar's *final* band**, not its freshly
  computed one — in Pine a `:=` reassignment is what enters series history.
- **`legacy_strength_labels`** reproduces the source's inverted "Strong Buy"
  logic (SMA8 >= SMA9 prints the *weaker* label). Diagnostic only; flipping it
  changes no trade.
- **TP needs no sign branching.** `(entry - stop) * N + entry` is correct for
  shorts because `entry - stop` is negative there.

### Deviations from the indicator

The indicator only draws labels, so anything about *taking* a trade is ours:

- Signals fill at the **next bar's open**, never the signal bar's close. The
  source's own header admits its signals flicker during bar formation, so a
  same-bar fill would backtest a signal that did not exist yet.
- `rr` picks which of the drawn 1:1 / 2:1 / 3:1 rungs to trade.
- `exit_on_opposite_signal`, `breakeven_r`, `trail_r` have no counterpart in
  the source and default to off.
- Stop/target ties within one bar resolve as a stop (same as the other two
  strategies' backtesters).

## Known-inert code in the source

Not ported, because it does nothing: 61-tier RSI bar colouring (with `tier49`
never rendered — line 197 repeats `tier48` — and `tier60`/`tier61` defined but
never plotted), the SMA(21)/34 ribbon, `psar`, `ocAvg`, `source`, `period`,
`trigger2`, and the `protradingart/pta_plot` import.
