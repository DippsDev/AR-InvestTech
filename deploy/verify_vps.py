"""VPS readiness check — run this on the VPS after setup, before trading.

Unlike backend/pre_live_check.py (which is US30-specific and places a real
smoke-test trade), this verifies the things that are specific to running
unattended on a rented box: every symbol in multi_symbol_targets.py resolves,
AutoTrading is actually enabled, the API is up and refusing unauthenticated
calls, and the run-state file will survive a reboot.

It places NO trades. Safe to run at any time, including on a live account.

Usage (from the repo root, venv active):
    python deploy/verify_vps.py
    python deploy/verify_vps.py --tunnel https://bot.yourdomain.com
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

FAILURES: list[str] = []
WARNINGS: list[str] = []


def section(title: str) -> None:
    print(f"\n{'=' * 68}\n {title}\n{'=' * 68}")


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    FAILURES.append(msg)


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")
    WARNINGS.append(msg)


def check_config() -> "object":
    section("1. CONFIGURATION")
    import config

    print(f"  Data dir   : {config.ENV_PATH.parent}")
    print(f"  Bind       : {config.BIND_HOST}:{config.BIND_PORT}")

    if config.MT5_LOGIN == 0 or not config.MT5_PASSWORD or not config.MT5_SERVER:
        fail("MT5_LOGIN / MT5_PASSWORD / MT5_SERVER missing from .env")
    else:
        ok(f"MT5 credentials present (login {config.MT5_LOGIN} @ {config.MT5_SERVER})")

    # The API is about to be reachable from the internet through the tunnel.
    # Without a token, anyone who learns the hostname can start/stop trading
    # and overwrite the MT5 password via POST /settings.
    if not config.API_TOKEN:
        fail("API_TOKEN is not set — the tunnel would expose trading controls to anyone")
    elif len(config.API_TOKEN) < 24:
        warn(f"API_TOKEN is only {len(config.API_TOKEN)} chars; use 32+ random chars")
    else:
        ok(f"API_TOKEN set ({len(config.API_TOKEN)} chars)")

    if config.BIND_HOST != "127.0.0.1":
        warn(f"Bound to {config.BIND_HOST} rather than loopback — the tunnel does not "
             "need this, and it exposes the port directly on the VPS network")
    else:
        ok("Bound to loopback (tunnel-fronted)")

    if "Trial" in config.MT5_SERVER or "Demo" in config.MT5_SERVER:
        print(f"\n  NOTE: '{config.MT5_SERVER}' looks like a DEMO server. Good for a "
              "soak test; switch deliberately when going live.")
    return config


def check_state_file(config) -> None:
    section("2. REBOOT RESILIENCE")
    from bridge import BotBridge

    state = Path(config.BOT_STATE_FILE)
    bridge = BotBridge()
    print(f"  State file : {state}")
    print(f"  Desired run state: {bridge._desired_running}")

    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        probe = state.with_suffix(".probe")
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        ok("Run-state directory is writable — bot will resume after reboot")
    except OSError as exc:
        fail(f"Cannot write run state ({exc}) — bot will NOT resume after a reboot")


def check_mt5(config) -> bool:
    section("3. MT5 TERMINAL")
    try:
        import MetaTrader5 as mt5
        from src.data_collector import connect_mt5
    except ImportError as exc:
        fail(f"MetaTrader5 package not importable: {exc}")
        return False

    if not connect_mt5(
        login=config.MT5_LOGIN or None,
        password=config.MT5_PASSWORD or None,
        server=config.MT5_SERVER or None,
        retries=2,
    ):
        fail(f"Cannot connect to MT5: {mt5.last_error()}")
        print("         Is terminal64.exe running and logged in on this desktop session?")
        return False
    ok("Connected to MT5")

    term = mt5.terminal_info()
    if term is None:
        fail("terminal_info() returned None")
        return False

    # This is the single most common reason an unattended bot places zero
    # trades while looking perfectly healthy in the dashboard.
    if not term.trade_allowed:
        fail("AutoTrading is DISABLED — the bot will never place an order. "
             "Enable the 'AutoTrading' toolbar button in MT5.")
    else:
        ok("AutoTrading enabled")

    if not term.connected:
        fail("Terminal is not connected to the broker")
    else:
        ok(f"Terminal connected to broker ({term.company})")

    account = mt5.account_info()
    if account is None:
        fail("account_info() returned None")
        return False
    print(f"\n  Account    : {account.login} ({account.server})")
    print(f"  Balance    : ${account.balance:,.2f}   Equity: ${account.equity:,.2f}")
    if account.trade_expert is False:
        fail("Algorithmic trading is disabled server-side for this account")
    return True


def check_symbols() -> None:
    section("4. TRADING SYMBOLS")
    import MetaTrader5 as mt5
    import config
    from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS

    groups = [("SB", SB_TARGETS), ("TL", TL_TARGETS)]
    if getattr(config, "MB_ENABLED", False):
        groups.append(("MB", MB_TARGETS))
    else:
        print("  (MB disabled — set MB_ENABLED=true to trade Mutanabby)\n")

    for strategy, targets in groups:
        for symbol in targets:
            info = mt5.symbol_info(symbol)
            if info is None:
                mt5.symbol_select(symbol, True)
                info = mt5.symbol_info(symbol)
            if info is None:
                fail(f"{strategy} {symbol}: not found on this broker — instance will be dropped")
                continue
            if info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                warn(f"{strategy} {symbol}: trade_mode={info.trade_mode} (not full trading)")
                continue
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                warn(f"{strategy} {symbol}: no tick data (market may be closed)")
                continue
            age = (datetime.now(timezone.utc)
                   - datetime.fromtimestamp(tick.time, tz=timezone.utc)).total_seconds()
            spread = (tick.ask - tick.bid) / info.point if info.point else 0
            state = "open" if age < 300 else f"stale {age / 60:.0f}m"
            ok(f"{strategy} {symbol}: bid={tick.bid} spread={spread:.1f}pts ({state})")


def check_api(config, tunnel: str | None) -> None:
    section("5. API SURFACE")

    def get(url: str, token: str | None = None, timeout: int = 10):
        req = urllib.request.Request(url)
        if token:
            req.add_header("X-API-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(400).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception as e:
            return None, str(e)

    local = f"http://127.0.0.1:{config.BIND_PORT}"
    status, body = get(f"{local}/health")
    if status != 200:
        fail(f"Local API not responding at {local}/health ({body or status}) — is the service running?")
        return
    ok(f"Local API up: {body.strip()}")

    # Auth must actually be enforced, not merely configured.
    status, _ = get(f"{local}/stats")
    if status == 401:
        ok("Unauthenticated /stats correctly rejected (401)")
    elif status == 200 and config.API_TOKEN:
        fail("Unauthenticated /stats returned 200 — token is NOT being enforced")
    elif status == 200:
        warn("Unauthenticated /stats returned 200 (no API_TOKEN configured)")

    if config.API_TOKEN:
        status, _ = get(f"{local}/stats", token=config.API_TOKEN)
        if status == 200:
            ok("Authenticated /stats returned 200")
        else:
            fail(f"Authenticated /stats returned {status} — token mismatch?")

    if tunnel:
        tunnel = tunnel.rstrip("/")
        status, body = get(f"{tunnel}/health", timeout=20)
        if status == 200:
            ok(f"Tunnel reachable: {tunnel}")
        else:
            fail(f"Tunnel {tunnel}/health returned {body or status} — is cloudflared running?")
        if not tunnel.startswith("https://"):
            fail("Tunnel URL is not https — the Vercel dashboard cannot call a plain-http backend")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a VPS is ready to run the bot unattended.")
    parser.add_argument("--tunnel", help="Public https URL to test end-to-end, e.g. https://bot.example.com")
    args = parser.parse_args()

    print("AR-InvestTech — VPS readiness check")
    print(f"Repo: {REPO_ROOT}")

    config = check_config()
    check_state_file(config)
    if check_mt5(config):
        check_symbols()
    check_api(config, args.tunnel)

    section("RESULT")
    if FAILURES:
        print(f"  {len(FAILURES)} FAILURE(S) — do not start trading until these are fixed:")
        for f in FAILURES:
            print(f"    - {f}")
    if WARNINGS:
        print(f"\n  {len(WARNINGS)} warning(s):")
        for w in WARNINGS:
            print(f"    - {w}")
    if not FAILURES:
        print("  All critical checks passed." if not WARNINGS
              else "  No critical failures; review the warnings above.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
