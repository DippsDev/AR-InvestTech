"""
Grid search over Silver Bullet parameters for US30m.
Run: python backtest_grid.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = str(ROOT / "us30_m5_3y.csv")

SCENARIOS = {
    "baseline":            ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "opposite_liquidity"],
    "aggressive_windows":  ["--windows", "03:00-04:00,04:00-05:00,10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "opposite_liquidity"],
    "mid_entry":           ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "mid", "--target-mode", "opposite_liquidity"],
    "far_edge_entry":      ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "far_edge", "--target-mode", "opposite_liquidity"],
    "rr_2":                ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "rr", "--rr", "2.0"],
    "rr_3":                ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "rr", "--rr", "3.0"],
    "no_be_trail":         ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "opposite_liquidity", "--breakeven-r", "0", "--trail-r", "0"],
    "fvg_5":               ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "opposite_liquidity", "--fvg-min-points", "5.0"],
    "fvg_12":              ["--windows", "10:00-11:00,11:00-12:00", "--entry-in-fvg", "near_edge", "--target-mode", "opposite_liquidity", "--fvg-min-points", "12.0"],
}


def run(name: str, args: list[str]) -> dict:
    print(f"\n=== Running: {name} ===", flush=True)
    json_path = str(HERE / f"grid_{name}.json")
    python_exe = str(ROOT / ".venv" / "Scripts" / "python.exe")
    cmd = [
        python_exe, "-m", "silver_bullet.run_backtest",
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
        result["error"] = proc.stderr[-2000:] if proc.stderr else "Unknown error"
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
    for name, args in SCENARIOS.items():
        results.append(run(name, args))

    with open(HERE / "backtest_grid_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n\n" + "=" * 80)
    print("  GRID SEARCH SUMMARY")
    print("=" * 80)
    print(f"{'Scenario':<22} {'Trades':>8} {'Win%':>8} {'Net P/L':>10} {'PF':>8} {'Max DD':>10} {'Avg R':>8}")
    print("-" * 80)
    for r in results:
        if "error" in r:
            print(f"{r['name']:<22} ERROR: {r['error'][:50]}")
            continue
        m = r.get("metrics", {})
        print(
            f"{r['name']:<22} "
            f"{m.get('num_trades', 0):>8} "
            f"{m.get('win_rate_pct', 0):>7.1f}% "
            f"${m.get('net_pnl_usd', 0):>8.2f} "
            f"{m.get('profit_factor', 0):>8.2f} "
            f"${m.get('max_drawdown_usd', 0):>8.2f} "
            f"{m.get('avg_r', 0):>8.3f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
