"""
Symbol discovery for Exness / MT5.

Lists every available symbol and highlights US30/Dow Jones candidates. Also
tries to add each candidate to Market Watch and fetch a live tick to confirm
it is actually tradeable.

Usage:
    python find_symbol.py
    python find_symbol.py --all          # dump every symbol to symbols.txt
    python find_symbol.py --term US30    # filter by custom term
"""
import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Add project root to path so we can import src modules when run directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_collector import connect_mt5, disconnect_mt5, list_symbols_with_details


def main() -> None:
    parser = argparse.ArgumentParser(description="List MT5 symbols and find US30/Dow Jones")
    parser.add_argument("--all", action="store_true", help="Write every symbol to symbols.txt")
    parser.add_argument("--term", default="", help="Additional search term")
    args = parser.parse_args()

    login = int(os.getenv("MT5_LOGIN", "0"))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")

    print(f"Connecting to {server} as {login}...")
    if not connect_mt5(login=login, password=password, server=server, retries=2):
        print(f"FAILED to connect: could not reach MT5 terminal")
        sys.exit(1)

    print("Connected successfully!\n")

    all_symbols = list_symbols_with_details()
    print(f"Total symbols on server: {len(all_symbols)}\n")

    if args.all:
        with open("symbols.txt", "w", encoding="utf-8") as f:
            for s in sorted(all_symbols, key=lambda x: x["name"]):
                f.write(
                    f"{s['name']:<20} spread={s['spread']:<6} "
                    f"point={s['point']:<12} digits={s['digits']} "
                    f"vol_min={s['volume_min']} step={s['volume_step']} "
                    f"visible={s['visible']}\n"
                )
        print("Wrote all symbols to symbols.txt\n")

    # Candidate filters for US30 / Dow Jones.
    search_tokens = ["30", "DOW", "DJ", "WALL", "US30", "DJ30", "DJIA"]
    if args.term:
        search_tokens.append(args.term.upper())

    candidates = []
    for s in all_symbols:
        name_upper = s["name"].upper()
        if any(token in name_upper for token in search_tokens):
            candidates.append(s)

    print(f"Found {len(candidates)} candidate symbol(s) for US30 / Dow Jones:\n")
    print(
        f"{'Symbol':<20} {'Spread':<8} {'Point':<14} {'Digits':<8} "
        f"{'Min Lot':<10} {'Step':<10} {'Visible':<8} {'Tickable':<8}"
    )
    print("-" * 100)

    import MetaTrader5 as mt5

    for s in sorted(candidates, key=lambda x: x["name"]):
        # Try to add to Market Watch and get a tick.
        mt5.symbol_select(s["name"], True)
        tick = mt5.symbol_info_tick(s["name"])
        tickable = "YES" if tick is not None else "NO"

        print(
            f"{s['name']:<20} {s['spread']:<8} {s['point']:<14.8f} "
            f"{s['digits']:<8} {s['volume_min']:<10} {s['volume_step']:<10} "
            f"{str(s['visible']):<8} {tickable:<8}"
        )

    print("\n" + "=" * 100)
    print("RECOMMENDATION:")
    print("1. Look for a symbol with Tickable=YES and a reasonable spread/point.")
    print("2. Common Exness names: US30, US30z (Zero account), US30.r (Raw account),")
    print("   US30.cash / US30Cash, WallStreet30, DJ30.")
    print("3. Set the working symbol in your .env file: SB_SYMBOL=<name>")
    print("4. If the symbol is visible in MT5's Market Watch but not here, right-click")
    print("   Market Watch → Show All, then re-run this script.")
    print("=" * 100)

    disconnect_mt5()


if __name__ == "__main__":
    main()
