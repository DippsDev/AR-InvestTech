"""
Quick trade test — connects to MT5, resolves the US30 symbol, places a
minimal market buy, and immediately closes it. Run once to confirm order
placement works before going live.

Usage: python test_trade.py
"""
import time
import os
import sys

from dotenv import load_dotenv
import MetaTrader5 as mt5

load_dotenv()

# Allow importing src helpers when running this script directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_collector import connect_mt5, disconnect_mt5, find_us30_symbol


LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER   = os.getenv("MT5_SERVER", "")

print(f"Connecting to {SERVER} as {LOGIN}...")
if not connect_mt5(login=LOGIN, password=PASSWORD, server=SERVER, retries=2):
    print(f"FAILED to connect: {mt5.last_error()}")
    sys.exit(1)

info = mt5.account_info()
print(f"Connected | Balance: ${info.balance:.2f} | Equity: ${info.equity:.2f}")

# Resolve symbol automatically.
SYMBOL = find_us30_symbol()
if SYMBOL is None:
    print("Could not resolve a US30/Dow Jones symbol.")
    print("Run: python find_symbol.py")
    disconnect_mt5()
    sys.exit(1)

print(f"Resolved symbol: {SYMBOL}")

mt5.symbol_select(SYMBOL, True)
sym  = mt5.symbol_info(SYMBOL)
tick = mt5.symbol_info_tick(SYMBOL)

if sym is None or tick is None:
    print("Could not get symbol/tick data after selection")
    disconnect_mt5()
    sys.exit(1)

lots  = sym.volume_min
price = tick.ask

# Use broker's minimum stop distance (trade_stops_level), with a safe buffer on top
min_stop_pts = max(sym.trade_stops_level, 50) * sym.point
sl = round(price - min_stop_pts * 3, sym.digits)
tp = round(price + min_stop_pts * 3, sym.digits)

print(f"\nSymbol info | point={sym.point} | digits={sym.digits} | min_stop_level={sym.trade_stops_level}")
print(f"Placing test BUY | {SYMBOL} | {lots} lots @ {price} | SL {sl} | TP {tp}")

result = mt5.order_send({
    "action":       mt5.TRADE_ACTION_DEAL,
    "symbol":       SYMBOL,
    "volume":       lots,
    "type":         mt5.ORDER_TYPE_BUY,
    "price":        price,
    "sl":           sl,
    "tp":           tp,
    "deviation":    50,
    "magic":        999999,
    "comment":      "test_trade",
    "type_time":    mt5.ORDER_TIME_GTC,
    "type_filling": mt5.ORDER_FILLING_IOC,
})

print(f"retcode : {result.retcode}")
print(f"comment : {result.comment}")

if result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"\nORDER PLACED SUCCESSFULLY — ticket #{result.order}")
    time.sleep(2)

    # Close it immediately
    positions = mt5.positions_get(ticket=result.order) or []
    if positions:
        pos   = positions[0]
        close = mt5.symbol_info_tick(SYMBOL).bid
        close_result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       SYMBOL,
            "volume":       pos.volume,
            "type":         mt5.ORDER_TYPE_SELL,
            "position":     pos.ticket,
            "price":        close,
            "deviation":    50,
            "magic":        999999,
            "comment":      "test_close",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })
        if close_result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Position closed cleanly.")
        else:
            print(f"Close failed: {close_result.retcode} — {close_result.comment}")
    else:
        print("Position not found (may have already closed via SL/TP)")
else:
    print(f"\nORDER FAILED")
    print("Common causes:")
    print("  10019 — not enough money (check margin requirements)")
    print("  10018 — market closed (check if US30 is tradeable now)")
    print("  10004 — requote (widen deviation or retry)")
    print("  10006 — rejected (check broker restrictions)")

disconnect_mt5()
