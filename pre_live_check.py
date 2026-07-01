"""
Pre-live verification checklist for the Silver Bullet bot.

Run this before enabling live trading to confirm:
  1. MT5 connection is stable
  2. US30 symbol resolves and is tradeable
  3. Order placement works (small demo trade)
  4. Session windows are configured correctly
  5. Risk settings are sane

Usage: python pre_live_check.py
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as root_config
from silver_bullet.config import SilverBulletConfig
from src.data_collector import connect_mt5, disconnect_mt5, find_us30_symbol, get_account_info


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def main() -> None:
    section("1. ENVIRONMENT / CONFIG")
    print(f"Server      : {root_config.MT5_SERVER}")
    print(f"Login       : {root_config.MT5_LOGIN}")
    print(f"SB_SYMBOL   : {root_config.SB_SYMBOL}")
    print(f"SB_RISK_PCT : {root_config.SB_RISK_PCT}%")
    print(f"Aggressive  : {root_config.SB_AGGRESSIVE}")
    print(f"Off-hours   : {root_config.SB_OFF_HOURS}")
    print(f"Market order: {root_config.SB_MARKET_ORDER}")

    if root_config.MT5_LOGIN == 0 or not root_config.MT5_PASSWORD or not root_config.MT5_SERVER:
        print("\n[FAIL] MT5_LOGIN / PASSWORD / SERVER missing from .env")
        sys.exit(1)

    if root_config.SB_RISK_PCT > 2.0:
        print(f"\n[WARN] SB_RISK_PCT is high ({root_config.SB_RISK_PCT}%). "
              "For a $100 account keep this at 1.0–2.0% max.")
    if root_config.SB_RISK_PCT < 0.5:
        print(f"\n[INFO] SB_RISK_PCT is {root_config.SB_RISK_PCT}%. "
              "On a $100 account 1.0% is a sensible starting point.")

    section("2. MT5 CONNECTION")
    if not connect_mt5(
        login=root_config.MT5_LOGIN,
        password=root_config.MT5_PASSWORD,
        server=root_config.MT5_SERVER,
        retries=2,
    ):
        print("[FAIL] Cannot connect to MT5. Common fixes:")
        print("       - Restart MT5 terminal and log in manually first.")
        print("       - Run: taskkill /F /IM terminal64.exe")
        print("       - Wait 10 s after MT5 starts before running this script.")
        sys.exit(1)
    print("[PASS] MT5 connected")

    section("3. ACCOUNT INFO")
    account = get_account_info()
    if account is None:
        print("[FAIL] account_info() returned None")
        disconnect_mt5()
        sys.exit(1)
    print(f"Balance      : ${account['balance']:.2f}")
    print(f"Equity       : ${account['equity']:.2f}")
    print(f"Free margin  : ${account['free_margin']:.2f}")
    print(f"Margin level : {account['margin_level']:.2f}%")

    floor = account["balance"] * (1.0 - root_config.SB_MAX_DRAWDOWN_PCT / 100.0)
    print(f"Drawdown halt: {root_config.SB_MAX_DRAWDOWN_PCT:.1f}% "
          f"(floor ${floor:.2f})")

    if account["balance"] < 25:
        print("\n[WARN] Balance is very low. One bad tick can wipe the account.")
    elif account["balance"] < 100:
        print("\n[WARN] Balance is under $100. Use the lowest risk % and expect "
              "minimum-lot sizing to dominate your risk.")
    else:
        print("\n[INFO] Balance looks OK for small-account testing.")

    section("4. SYMBOL RESOLUTION")
    symbol = find_us30_symbol()
    if symbol is None:
        print("[FAIL] No US30/Dow Jones symbol found.")
        print("       Run: python find_symbol.py")
        disconnect_mt5()
        sys.exit(1)
    print(f"[PASS] Resolved symbol: {symbol}")

    sym_info = mt5.symbol_info(symbol)
    if sym_info is None:
        print("[FAIL] symbol_info() returned None after resolution")
        disconnect_mt5()
        sys.exit(1)

    print(f"Point       : {sym_info.point}")
    print(f"Digits      : {sym_info.digits}")
    print(f"Min volume  : {sym_info.volume_min}")
    print(f"Volume step : {sym_info.volume_step}")
    print(f"Max volume  : {sym_info.volume_max}")
    print(f"Tick value  : {sym_info.trade_tick_value}")
    print(f"Tick size   : {sym_info.trade_tick_size}")
    print(f"Stop level  : {sym_info.trade_stops_level}")

    # Estimate the dollar risk of a minimum-lot trade with a 20-point stop.
    # This helps the user see whether 1% risk is even achievable on $100.
    if sym_info.trade_tick_value and sym_info.trade_tick_size:
        value_per_pt = sym_info.trade_tick_value / sym_info.trade_tick_size
        est_risk_20pts = sym_info.volume_min * 20.0 * value_per_pt
        print(f"\n[INFO] A {sym_info.volume_min}-lot US30 trade with a 20-pt stop "
              f"risks roughly ${est_risk_20pts:.2f}.")
        target_risk = account["balance"] * (root_config.SB_RISK_PCT / 100.0)
        if est_risk_20pts > target_risk * 1.5:
            print("[WARN] Minimum-lot risk is much larger than your target risk. "
                  "The bot will floor to volume_min; expect bigger % swings.")

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("[FAIL] No live tick data. Market may be closed or symbol not subscribed.")
        disconnect_mt5()
        sys.exit(1)
    print(f"[PASS] Live tick | Bid={tick.bid} Ask={tick.ask} Spread={tick.ask - tick.bid}")

    section("5. SESSION WINDOWS (America/New_York)")
    cfg = SilverBulletConfig()
    if root_config.SB_AGGRESSIVE:
        cfg.windows = [
            ("03:00", "04:00"), ("04:00", "05:00"),
            ("10:00", "11:00"), ("11:00", "12:00"),
        ]
    now_ny = datetime.now(ZoneInfo("America/New_York"))
    print(f"Current NY time: {now_ny.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("Active windows:")
    for start, end in cfg.windows:
        print(f"  {start} - {end} ET")

    section("6. MARGIN / LOT SANITY CHECK")
    # A rough margin estimate: Exness US30 margin is typically ~0.5–1% of
    # notional.  This is only an order-of-magnitude check.
    price = tick.ask
    nominal = sym_info.volume_min * price * 1000.0  # common CFD notional multiplier
    est_margin = nominal * 0.01
    free_margin = account["free_margin"]
    print(f"Estimated margin for {sym_info.volume_min} lot: ~${est_margin:.2f} "
          f"(free margin: ${free_margin:.2f})")
    if est_margin > free_margin * 0.5:
        print("[WARN] Minimum-lot margin is a large chunk of free margin. "
              "Consider funding the account a bit more.")

    section("7. ORDER PLACEMENT SMOKE TEST")
    lots = sym_info.volume_min
    min_stop_pts = max(sym_info.trade_stops_level, 50) * sym_info.point
    sl = round(price - min_stop_pts * 3, sym_info.digits)
    tp = round(price + min_stop_pts * 3, sym_info.digits)

    print(f"Sending test BUY | {symbol} | {lots} lots @ {price} | SL {sl} | TP {tp}")
    result = mt5.order_send({
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       symbol,
        "volume":       lots,
        "type":         mt5.ORDER_TYPE_BUY,
        "price":        price,
        "sl":           sl,
        "tp":           tp,
        "deviation":    50,
        "magic":        888888,
        "comment":      "prelive_test",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    })

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[FAIL] Order failed: {result.retcode} — {result.comment}")
        print("Common retcodes:")
        print("  10018 — market closed")
        print("  10019 — not enough money")
        print("  10014 — invalid stops")
        print("  10027 — disabled (enable AutoTrading / algorithmic trading)")
        disconnect_mt5()
        sys.exit(1)

    print(f"[PASS] Order placed — ticket #{result.order}")
    print("Closing immediately...")
    time.sleep(1)

    positions = mt5.positions_get(ticket=result.order) or []
    if positions:
        pos = positions[0]
        close_result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL,
            "position":     pos.ticket,
            "price":        mt5.symbol_info_tick(symbol).bid,
            "deviation":    50,
            "magic":        888888,
            "comment":      "prelive_close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if close_result.retcode == mt5.TRADE_RETCODE_DONE:
            print("[PASS] Position closed")
        else:
            print(f"[WARN] Close failed: {close_result.retcode} — {close_result.comment}")
            print("       You may need to close it manually in MT5.")
    else:
        print("[WARN] Position not found for closure (may have closed instantly)")

    section("8. MANUAL CHECKLIST")
    print("Before going live on Monday, confirm:")
    print("  □ You are on a DEMO account (account number matches demo)")
    print("  □ MT5 terminal: Tools → Options → Expert Advisors →")
    print("      'Allow WebRequest for listed URL' (if bridge uses web)")
    print("  □ MT5 terminal: 'AutoTrading' button is pressed/green")
    print("  □ MT5 terminal: Tools → Options → Expert Advisors →")
    print("      'Allow algorithmic trading' is checked")
    print("  □ US30 chart is open on M5 in MT5")
    print("  □ No LiveUpdate / modal dialogs are blocking MT5")
    print("  □ You have tested with SB_RISK_PCT=1.0 first")
    print("  □ Exness server ends in -Trial for demo or -Live for real (check .env)")
    print("  □ Exness symbol for Dow is added to Market Watch (often US30z or US30.cash)")
    print("  □ Account leverage is known (1:200/1:unlimited common on Exness)")
    print("  □ Swap-free / Islamic account status confirmed if holding past 17:00 ET")
    print("  □ Bot is started at least 5 minutes before 10:00 AM ET")

    section("RESULT")
    print("[PASS] All automated checks passed. Review the manual checklist above.")

    disconnect_mt5()


if __name__ == "__main__":
    import time
    main()
