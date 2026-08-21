"""
Trade performance report.

Pulls the bot's full deal history straight from the MT5 terminal (no 30-day
window like the dashboard), pairs open/close deals into closed trades, and
prints win rate, profit factor, expectancy and per-strategy / per-symbol
breakdowns. Optionally exports the full trade log to CSV.

Bot trades are identified the same way bridge.py does: by magic number
(SB/TL/MB), falling back to the locally recorded tickets in
bot_tickets.json for brokers that zero out `magic` on deals.

Usage:
  python trade_report.py                          # all history the terminal holds
  python trade_report.py --days 90                # last 90 days
  python trade_report.py --from 2025-01-01 --to 2025-06-30
  python trade_report.py --strategy SB            # one strategy only
  python trade_report.py --csv trades.csv         # export trade log
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import MetaTrader5 as mt5

from src.data_collector import connect_mt5
from src.ticket_store import load_tickets

# magic number → strategy tag, mirroring the live adapters.
MAGIC_STRATEGY = {}
try:
    from silver_bullet.live_adapter import SB_MAGIC
    MAGIC_STRATEGY[SB_MAGIC] = "SB"
except Exception:
    pass
try:
    from trendline.live_adapter import TL_MAGIC
    MAGIC_STRATEGY[TL_MAGIC] = "TL"
except Exception:
    pass
try:
    from mutanabby.live_adapter import MB_MAGIC
    MAGIC_STRATEGY[MB_MAGIC] = "MB"
except Exception:
    pass

CLOSE_ENTRIES = {mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bot trade performance report (full MT5 history).")
    p.add_argument("--days", type=int, default=None, help="Look back N days (default: all history).")
    p.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD.")
    p.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD (default: now).")
    p.add_argument("--strategy", choices=["SB", "TL", "MB"], default=None, help="Only this strategy.")
    p.add_argument("--csv", dest="csv_path", default=None, help="Export closed trades to this CSV path.")
    return p.parse_args()


def resolve_range(args) -> tuple[datetime, datetime]:
    # Same convention as bridge.py: naive local datetimes, upper bound padded
    # +6h because some broker servers timestamp deals ahead of true UTC.
    to_dt = datetime.now() + timedelta(hours=6)
    if args.date_to:
        to_dt = datetime.strptime(args.date_to, "%Y-%m-%d") + timedelta(days=1)
    if args.date_from:
        from_dt = datetime.strptime(args.date_from, "%Y-%m-%d")
    elif args.days:
        from_dt = datetime.now() - timedelta(days=args.days)
    else:
        from_dt = datetime(2000, 1, 1)  # effectively "everything the terminal holds"
    return from_dt, to_dt


def strategy_for(deals: list, ticket_strategies: dict[int, str]) -> str:
    for d in deals:
        if d.magic in MAGIC_STRATEGY:
            return MAGIC_STRATEGY[d.magic]
    for d in deals:
        if d.position_id in ticket_strategies:
            return ticket_strategies[d.position_id]
    return "??"


def build_trades(from_dt: datetime, to_dt: datetime) -> tuple[list[dict], int]:
    """Closed trades whose close happened inside [from_dt, to_dt].

    Returns (trades, still_open_count). A position that closed inside the
    window gets its full history re-fetched by position_id so an entry taken
    before `from_dt` still contributes its real open price and volume.
    """
    deals = mt5.history_deals_get(from_dt, to_dt) or []

    # Which of these belong to the bot (bridge.py's filter: magic OR ticket).
    known_tickets = load_tickets()
    ticket_strategies: dict[int, str] = {}
    for tag in ("SB", "TL", "MB"):
        for t in load_tickets(tag):
            ticket_strategies[t] = tag

    bot_deals = [d for d in deals if d.magic in MAGIC_STRATEGY or d.position_id in known_tickets]

    closed_pids = {d.position_id for d in bot_deals if d.entry in CLOSE_ENTRIES}
    trades: list[dict] = []
    still_open = 0

    for pid in sorted(closed_pids):
        full = mt5.history_deals_get(position=pid) or []
        opens = [d for d in full if d.entry == mt5.DEAL_ENTRY_IN]
        closes = [d for d in full if d.entry in CLOSE_ENTRIES]
        open_vol = sum(d.volume for d in opens)
        close_vol = sum(d.volume for d in closes)
        if not opens or not closes:
            continue
        if close_vol < open_vol - 1e-9:
            still_open += 1  # partially closed legs still running
            continue

        o = opens[0]
        side = "BUY" if o.type == mt5.DEAL_TYPE_BUY else "SELL"
        entry_px = sum(d.price * d.volume for d in opens) / open_vol
        exit_px = sum(d.price * d.volume for d in closes) / close_vol
        gross = sum(d.profit for d in full)
        commission = sum(d.commission for d in full)
        swap = sum(d.swap for d in full)
        fee = sum(getattr(d, "fee", 0.0) for d in full)
        net = gross + commission + swap + fee
        points = (exit_px - entry_px) * (1 if side == "BUY" else -1)

        trades.append({
            "position_id": pid,
            "strategy": strategy_for(full, ticket_strategies),
            "symbol": o.symbol,
            "side": side,
            "lots": open_vol,
            "open_time": datetime.fromtimestamp(o.time),
            "close_time": datetime.fromtimestamp(max(d.time for d in closes)),
            "entry": entry_px,
            "exit": exit_px,
            "points": points,
            "gross": gross,
            "commission": commission,
            "swap": swap,
            "fee": fee,
            "net": net,
            "win": net > 0,
        })

    trades.sort(key=lambda t: t["close_time"])
    return trades, still_open


def summarize(trades: list[dict]) -> dict:
    wins = [t for t in trades if t["net"] > 0]
    losses = [t for t in trades if t["net"] < 0]
    gross_profit = sum(t["net"] for t in wins)
    gross_loss = sum(t["net"] for t in losses)
    net = gross_profit + gross_loss
    n = len(trades)
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "flat": n - len(wins) - len(losses),
        "win_rate": (len(wins) / n * 100) if n else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net": net,
        "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss else None,
        "avg_win": (gross_profit / len(wins)) if wins else 0.0,
        "avg_loss": (gross_loss / len(losses)) if losses else 0.0,
        "expectancy": (net / n) if n else 0.0,
        "best": max(trades, key=lambda t: t["net"], default=None),
        "worst": min(trades, key=lambda t: t["net"], default=None),
    }


def fmt_money(v: float) -> str:
    return f"+${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}"


def print_group(title: str, trades: list[dict]) -> None:
    s = summarize(trades)
    pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "  inf (no losses)"
    print(f"\n{title}")
    print("-" * len(title))
    if not s["n"]:
        print("  no closed trades")
        return
    print(f"  Closed trades : {s['n']}  ({s['wins']}W / {s['losses']}L / {s['flat']} flat)")
    print(f"  Win rate      : {s['win_rate']:.1f}%")
    print(f"  Net P&L       : {fmt_money(s['net'])}")
    print(f"  Gross profit  : {fmt_money(s['gross_profit'])}")
    print(f"  Gross loss    : {fmt_money(s['gross_loss'])}")
    print(f"  Profit factor : {pf}")
    print(f"  Avg win       : {fmt_money(s['avg_win'])}")
    print(f"  Avg loss      : {fmt_money(s['avg_loss'])}")
    print(f"  Expectancy    : {fmt_money(s['expectancy'])} / trade")
    if s["best"]:
        b = s["best"]
        print(f"  Best trade    : {fmt_money(b['net'])}  {b['side']} {b['symbol']} #{b['position_id']}")
    if s["worst"]:
        w = s["worst"]
        print(f"  Worst trade   : {fmt_money(w['net'])}  {w['side']} {w['symbol']} #{w['position_id']}")


def print_table(title: str, groups: dict[str, list[dict]]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    print(f"  {'name':<10} {'trades':>6} {'win%':>7} {'net P&L':>12} {'PF':>7}")
    rows = sorted(groups.items(), key=lambda kv: summarize(kv[1])["net"], reverse=True)
    for name, ts in rows:
        s = summarize(ts)
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "inf"
        print(f"  {name:<10} {s['n']:>6} {s['win_rate']:>6.1f}% {fmt_money(s['net']):>12} {pf:>7}")


def export_csv(path: str, trades: list[dict]) -> None:
    fields = ["position_id", "strategy", "symbol", "side", "lots",
              "open_time", "close_time", "entry", "exit", "points",
              "gross", "commission", "swap", "fee", "net", "win"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for t in trades:
            row = dict(t)
            row["open_time"] = t["open_time"].strftime("%Y-%m-%d %H:%M:%S")
            row["close_time"] = t["close_time"].strftime("%Y-%m-%d %H:%M:%S")
            row["entry"] = f"{t['entry']:.2f}"
            row["exit"] = f"{t['exit']:.2f}"
            row["points"] = f"{t['points']:.1f}"
            for k in ("gross", "commission", "swap", "fee", "net"):
                row[k] = f"{t[k]:.2f}"
            w.writerow(row)


def main() -> int:
    args = parse_args()
    from_dt, to_dt = resolve_range(args)

    ok = connect_mt5(
        login=config.MT5_LOGIN or None,
        password=config.MT5_PASSWORD or None,
        server=config.MT5_SERVER or None,
        retries=2,
    )
    if not ok:
        print(f"Could not connect to MT5: {mt5.last_error()}")
        return 1

    try:
        info = mt5.account_info()
        trades, still_open = build_trades(from_dt, to_dt)
    finally:
        mt5.shutdown()

    if args.strategy:
        trades = [t for t in trades if t["strategy"] == args.strategy]

    period_to = min(to_dt, datetime.now())
    print("=" * 66)
    print(" Trade Performance Report")
    print(f" Period : {from_dt:%Y-%m-%d} -> {period_to:%Y-%m-%d}")
    if info:
        print(f" Account: {info.login} @ {info.server} | balance ${info.balance:,.2f} | equity ${info.equity:,.2f}")
    print("=" * 66)

    print_group("Overall", trades)

    by_strategy: dict[str, list[dict]] = defaultdict(list)
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        by_strategy[t["strategy"]].append(t)
        by_symbol[t["symbol"]].append(t)
    if not args.strategy and len(by_strategy) > 1:
        print_table("By strategy", by_strategy)
    if len(by_symbol) > 1:
        print_table("By symbol", by_symbol)

    if still_open:
        print(f"\nNote: {still_open} position(s) still open or partially closed — excluded above.")

    if args.csv_path:
        export_csv(args.csv_path, trades)
        print(f"\nTrade log exported to {args.csv_path} ({len(trades)} trades)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
