"""
Grid search for off-hours scalp parameters.

Run: python backtests/off_hours_grid.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
DATA = str(ROOT / "data" / "us30_m5_200d.csv")
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

# Search space for off-hours scalp parameters
RRS = ["1.0", "1.3", "1.6"]
FVGS = ["6.0", "8.0", "12.0"]
BES = ["0.2", "0.3"]
TRAILS = ["0.10", "0.15"]


def run(name: str, args: list[str]) -> dict:
    print(f"\n=== Running: {name} ===", flush=True)
    json_path = str(HERE / f"offh_{name}.json")
    cmd = [
        PYTHON, "-m", "silver_bullet.run_backtest",
        "--data", DATA,
        "--symbol", "US30",
        "--show-trades", "0",
        "--save-json", json_path,
        "--off-hours",
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
            result["args"] = args
        except Exception as exc:
            result["error"] = f"Failed to read JSON: {exc}"
    else:
        result["error"] = "JSON output not created"

    return result


def main() -> int:
    results = []
    for rr in RRS:
        for fvg in FVGS:
            for be in BES:
                for trail in TRAILS:
                    name = f"rr{rr}_fvg{fvg}_be{be}_tr{trail}"
                    args = [
                        "--off-hours-rr", rr,
                        "--off-hours-fvg-min", fvg,
                        "--off-hours-breakeven", be,
                        "--off-hours-trail", trail,
                    ]
                    results.append(run(name, args))

    with open(HERE / "off_hours_grid_results.json", "w") as f:
        json.dump(results, f, indent=2)

    valid = [r for r in results if "metrics" in r]

    # Composite balance score: profit factor weighted by return/drawdown ratio.
    def score(r: dict) -> float:
        m = r["metrics"]
        pnl = m.get("net_pnl_usd", 0)
        dd = m.get("max_drawdown_usd", 1)
        pf = m.get("profit_factor", 0)
        # Avoid division by zero and penalize negative/zero PF.
        if dd <= 0 or pf <= 0:
            return -9999
        return (pnl / dd) * pf

    valid.sort(key=score, reverse=True)

    print("\n\n" + "=" * 110)
    print("  OFF-HOURS GRID RESULTS — sorted by balance score (PNL/DD × Profit Factor)")
    print("=" * 110)
    print(f"{'Config':<34} {'Trades':>8} {'Win%':>8} {'Net P/L':>10} {'PF':>8} {'Max DD':>10} {'Avg R':>8} {'Score':>10}")
    print("-" * 110)
    for r in valid[:15]:
        m = r["metrics"]
        print(
            f"{r['name']:<34} "
            f"{m.get('num_trades', 0):>8} "
            f"{m.get('win_rate_pct', 0):>7.1f}% "
            f"${m.get('net_pnl_usd', 0):>8.2f} "
            f"{m.get('profit_factor', 0):>8.2f} "
            f"${m.get('max_drawdown_usd', 0):>8.2f} "
            f"{m.get('avg_r', 0):>8.3f} "
            f"{score(r):>10.2f}"
        )

    if valid:
        best = valid[0]
        print("\n" + "=" * 110)
        print(f"BEST BALANCED CONFIG: {best['name']}")
        print(f"  Args: {' '.join(best['args'])}")
        print(f"  Net P/L:      ${best['metrics']['net_pnl_usd']:.2f}")
        print(f"  Profit factor: {best['metrics']['profit_factor']}")
        print(f"  Max drawdown: ${best['metrics']['max_drawdown_usd']:.2f}")
        print(f"  Win rate:      {best['metrics']['win_rate_pct']:.1f}%")
        print(f"  Avg R:         {best['metrics']['avg_r']:.3f}")
        print("=" * 110)

    return 0


if __name__ == "__main__":
    sys.exit(main())
