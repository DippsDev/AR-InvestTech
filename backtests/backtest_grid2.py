"""
Focused grid search for best Silver Bullet config on US30m.
Run: python backtest_grid2.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = str(ROOT / "us30_m5_3y.csv")
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# Phase 1: entry mode × target mode (stop_buffer=1.0, fvg=8.0 baseline)
PHASE1 = []
for entry in ["near_edge", "mid", "far_edge"]:
    for target in ["opposite_liquidity", "rr"]:
        for rr in (["1.5"] if target == "rr" else ["2.0"]):
            name = f"{entry}_t{target[:3]}{rr if target == 'rr' else ''}"
            args = [
                "--windows", "10:00-11:00,11:00-12:00",
                "--entry-in-fvg", entry,
                "--target-mode", target,
            ]
            if target == "rr":
                args += ["--rr", rr]
            PHASE1.append((name, args))

# Add a couple more rr values for mid entry
for rr in ["2.0", "2.5", "3.0"]:
    PHASE1.append((f"mid_rr{rr}", [
        "--windows", "10:00-11:00,11:00-12:00",
        "--entry-in-fvg", "mid",
        "--target-mode", "rr",
        "--rr", rr,
    ]))

# Phase 2: variations around best from phase 1
PHASE2 = []
for buf in ["0.5", "1.0", "2.0"]:
    PHASE2.append((f"mid_opp_buf{buf}", [
        "--windows", "10:00-11:00,11:00-12:00",
        "--entry-in-fvg", "mid",
        "--target-mode", "opposite_liquidity",
        "--stop-buffer", buf,
    ]))
for fvg in ["4.0", "6.0", "10.0", "14.0"]:
    PHASE2.append((f"mid_opp_fvg{fvg}", [
        "--windows", "10:00-11:00,11:00-12:00",
        "--entry-in-fvg", "mid",
        "--target-mode", "opposite_liquidity",
        "--fvg-min-points", fvg,
    ]))
for min_risk in ["3.0", "4.0", "6.0", "8.0"]:
    PHASE2.append((f"mid_opp_risk{min_risk}", [
        "--windows", "10:00-11:00,11:00-12:00",
        "--entry-in-fvg", "mid",
        "--target-mode", "opposite_liquidity",
        "--min-risk", min_risk,
    ]))

SCENARIOS = PHASE1 + PHASE2


def run(name: str, args: list[str]) -> dict:
    print(f"\n=== Running: {name} ===", flush=True)
    json_path = str(HERE / f"grid2_{name}.json")
    cmd = [
        PYTHON, "-m", "silver_bullet.run_backtest",
        "--data", DATA,
        "--symbol", "US30m",
        "--risk", "0.27",
        "--spread", "2.0",
        "--commission", "0.05",
        "--slippage", "1.0",
        "--show-trades", "0",
        "--save-json", json_path,
    ] + args

    proc = subprocess.run(cmd, capture_output=True, text=True)
    result = {"name": name, "returncode": proc.returncode}

    if proc.returncode != 0:
        result["error"] = proc.stderr[-1500:] if proc.stderr else "Unknown error"
        return result

    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
            result["metrics"] = data.get("metrics", {})
        except Exception as exc:
            result["error"] = f"Failed to read JSON: {exc}"
    else:
        result["error"] = "JSON output not created"

    return result


def main() -> int:
    results = []
    for name, args in SCENARIOS:
        results.append(run(name, args))

    with open(HERE / "backtest_grid2_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Sort by net P/L descending
    valid = [r for r in results if "metrics" in r]
    valid.sort(key=lambda r: r["metrics"].get("net_pnl_usd", -999), reverse=True)

    print("\n\n" + "=" * 90)
    print("  GRID SEARCH RESULTS — sorted by Net P/L")
    print("=" * 90)
    print(f"{'Scenario':<26} {'Trades':>8} {'Win%':>8} {'Net P/L':>10} {'PF':>8} {'Max DD':>10} {'Avg R':>8}")
    print("-" * 90)
    for r in valid:
        m = r["metrics"]
        print(
            f"{r['name']:<26} "
            f"{m.get('num_trades', 0):>8} "
            f"{m.get('win_rate_pct', 0):>7.1f}% "
            f"${m.get('net_pnl_usd', 0):>8.2f} "
            f"{m.get('profit_factor', 0):>8.2f} "
            f"${m.get('max_drawdown_usd', 0):>8.2f} "
            f"{m.get('avg_r', 0):>8.3f}"
        )

    if valid:
        best = valid[0]
        print("\n" + "=" * 90)
        print(f"BEST CONFIG: {best['name']}")
        print(f"  Net P/L: ${best['metrics']['net_pnl_usd']:.2f}")
        print(f"  Profit factor: {best['metrics']['profit_factor']}")
        print(f"  Max drawdown: ${best['metrics']['max_drawdown_usd']:.2f}")
        print("=" * 90)

    return 0


if __name__ == "__main__":
    sys.exit(main())
