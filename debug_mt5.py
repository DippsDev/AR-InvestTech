"""
MT5 connection debugger.

Run this when you keep getting IPC timeout. It will:
  1. Show running MT5 processes
  2. Find terminal64.exe on disk
  3. Try several ways to initialize MT5
  4. Print the exact error for each attempt

Usage: python debug_mt5.py
"""
import os
import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as root_config
import MetaTrader5 as mt5


def print_section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def running_mt5_processes() -> list[dict]:
    procs = []
    try:
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='terminal64.exe' OR name='terminal.exe' OR name='MetaTrader5.exe'",
                "get",
                "ProcessId,ExecutablePath,Name",
                "/format:csv",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 4 and parts[0] != "Node":
                # CSV format: Node,Name,ProcessId,ExecutablePath
                procs.append({
                    "name": parts[1],
                    "pid": parts[2],
                    "path": parts[3],
                })
    except Exception as exc:
        print(f"Could not query processes: {exc}")
    return procs


def find_terminal_on_disk() -> list[str]:
    paths = []
    if root_config.MT5_PATH and os.path.isfile(root_config.MT5_PATH):
        paths.append(root_config.MT5_PATH)

    roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
    ]

    candidates = []
    import glob
    for pf in (r"C:\Program Files", r"C:\Program Files (x86)"):
        if not os.path.isdir(pf):
            continue
        try:
            candidates.extend(glob.glob(os.path.join(pf, "*", "terminal64.exe")))
        except Exception:
            pass

    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        candidates.extend([
            os.path.join(root, "MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness MT5", "terminal64.exe"),
            os.path.join(root, "Exness MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness", "MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness MT5 Terminal", "terminal64.exe"),
            os.path.join(root, "MetaQuotes", "MetaTrader 5", "terminal64.exe"),
        ])

    for p in set(candidates):
        if p and os.path.isfile(p) and p not in paths:
            paths.append(p)
    return paths


def try_init(description: str, **kwargs) -> bool:
    try:
        mt5.shutdown()
    except Exception:
        pass
    print(f"\nTrying: {description}")
    print(f"  kwargs = {kwargs}")
    try:
        ok = mt5.initialize(**kwargs)
        if ok:
            info = mt5.account_info()
            print(f"  [OK] Connected | {info.server if info else 'no account info'} | "
                  f"Balance ${info.balance:.2f}" if info else "  [OK] Connected")
            mt5.shutdown()
            return True
        else:
            err = mt5.last_error()
            print(f"  [FAIL] {err}")
            return False
    except Exception as exc:
        print(f"  [ERROR] {exc}")
        return False


def main() -> None:
    print_section("MT5 CONNECTION DEBUG")
    print(f"MT5_LOGIN    = {root_config.MT5_LOGIN}")
    print(f"MT5_SERVER   = {root_config.MT5_SERVER}")
    print(f"MT5_PATH     = {root_config.MT5_PATH or '(not set)'}")
    print(f"SB_SYMBOL    = {root_config.SB_SYMBOL}")

    print_section("RUNNING MT5 PROCESSES")
    procs = running_mt5_processes()
    if procs:
        for p in procs:
            print(f"  PID {p['pid']:<8} {p['name']:<20} {p['path']}")
    else:
        print("  No MT5 processes found.")

    print_section("terminal64.exe FOUND ON DISK")
    paths = find_terminal_on_disk()
    if paths:
        for p in paths:
            print(f"  {p}")
    else:
        print("  terminal64.exe not found in common locations.")
        print("  Please find it manually (right-click MT5 shortcut → Open file location)")
        print("  and add this line to .env:")
        print("  MT5_PATH=C:\\Path\\To\\terminal64.exe")

    print_section("INITIALIZATION ATTEMPTS")
    login = root_config.MT5_LOGIN
    password = root_config.MT5_PASSWORD
    server = root_config.MT5_SERVER

    # Strategy 1: No credentials, no path (relies on logged-in terminal)
    try_init("No credentials, no path")

    # Strategy 2: No credentials, with each discovered path
    for p in paths:
        try_init(f"No credentials, path={p}", path=p)

    # Strategy 3: With credentials, no path
    if login and password and server:
        try_init(f"With credentials, no path", login=login, password=password, server=server)

    # Strategy 4: With credentials and each path
    for p in paths:
        if login and password and server:
            try_init(f"With credentials, path={p}", path=p, login=login, password=password, server=server)

    print_section("RECOMMENDATION")
    success_no_creds = any("[OK] Connected" in line for line in [
        # We can't easily reuse results here, so just give generic advice.
    ])

    if not paths:
        print("Cannot find terminal64.exe. Set MT5_PATH in .env to the exact path.")
    else:
        print("The correct terminal is probably one of these:")
        for p in paths:
            marker = "  <- likely correct" if "EXNESS" in p.upper() else ""
            print(f"  {p}{marker}")
        print("\nSteps:")
        print("1. Add this line to .env:")
        exness_paths = [p for p in paths if "EXNESS" in p.upper()]
        preferred = exness_paths[0] if exness_paths else paths[0]
        print(f"   MT5_PATH={preferred}")
        print("2. Start MT5 manually from that path, log in, wait 10s.")
        print("3. Run your bot/scripts WITHOUT launching a second terminal.")
        print("4. The bot will attach to the already-logged-in terminal (no IPC timeout).")


if __name__ == "__main__":
    main()
