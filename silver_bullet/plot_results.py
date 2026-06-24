"""
Backtest results visualisation — produces a multi-panel performance dashboard.

Usage (from run_backtest.py):
    from .plot_results import plot_backtest
    plot_backtest(trades, metrics)
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
from matplotlib.patches import Patch

from .backtest import Trade


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plot_backtest(
    trades: List[Trade],
    metrics: dict,
    show: bool = True,
    save_path: Optional[str] = None,
) -> None:
    """Render a five-panel performance dashboard for a completed backtest."""
    if not trades:
        print("No trades — nothing to plot.")
        return

    pnls = np.array([t.pnl_dollars for t in trades], dtype=float)
    cum  = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd   = cum - peak          # always ≤ 0
    rs   = np.array([t.r_multiple for t in trades], dtype=float)
    exit_times = [t.exit_time for t in trades]
    monthly    = _monthly_pnl(trades)

    fig = plt.figure(figsize=(17, 11), facecolor="#0f1117")
    fig.suptitle(
        "Silver Bullet Strategy — Backtest Dashboard",
        fontsize=15, fontweight="bold", color="white", y=0.98,
    )

    gs = gridspec.GridSpec(
        3, 3,
        figure=fig,
        hspace=0.52,
        wspace=0.35,
        top=0.93, bottom=0.07, left=0.07, right=0.97,
    )

    ax_eq  = fig.add_subplot(gs[0, :])          # equity + drawdown (full width)
    ax_bar = fig.add_subplot(gs[1, :2])         # per-trade P&L bars
    ax_st  = fig.add_subplot(gs[1, 2])          # stats text box
    ax_rr  = fig.add_subplot(gs[2, 0])          # R-multiple histogram
    ax_mo  = fig.add_subplot(gs[2, 1])          # monthly P&L bars
    ax_ex  = fig.add_subplot(gs[2, 2])          # exit breakdown pie

    _style_axes(fig, [ax_eq, ax_bar, ax_st, ax_rr, ax_mo, ax_ex])

    _plot_equity(ax_eq, exit_times, cum, dd)
    _plot_trade_bars(ax_bar, trades, pnls)
    _plot_stats(ax_st, metrics)
    _plot_r_histogram(ax_rr, rs)
    _plot_monthly(ax_mo, monthly)
    _plot_exit_pie(ax_ex, metrics["exit_breakdown"])

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Chart saved to {save_path}")

    if show:
        plt.show()
    else:
        plt.close(fig)


# ---------------------------------------------------------------------------
# Panel helpers
# ---------------------------------------------------------------------------

_GREEN = "#26a69a"
_RED   = "#ef5350"
_GREY  = "#90a4ae"
_BG    = "#1e2130"
_TEXT  = "#e0e0e0"
_ACCENT = "#42a5f5"


def _style_axes(fig, axes):
    for ax in axes:
        ax.set_facecolor(_BG)
        ax.tick_params(colors=_GREY, labelsize=8)
        ax.xaxis.label.set_color(_GREY)
        ax.yaxis.label.set_color(_GREY)
        ax.title.set_color(_TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor("#2d3348")


def _plot_equity(ax, times, cum, dd):
    ax.set_title("Equity Curve & Drawdown", fontsize=10, pad=6)

    # Cumulative P&L line
    ax.plot(range(len(cum)), cum, color=_ACCENT, linewidth=1.5, label="Cumulative P&L")
    ax.axhline(0, color=_GREY, linewidth=0.6, linestyle="--", alpha=0.5)

    # Colour fill: green above 0, red below
    ax.fill_between(range(len(cum)), cum, 0,
                    where=(cum >= 0), color=_GREEN, alpha=0.18)
    ax.fill_between(range(len(cum)), cum, 0,
                    where=(cum < 0),  color=_RED,   alpha=0.18)

    # Drawdown on secondary y-axis
    ax2 = ax.twinx()
    ax2.set_facecolor(_BG)
    ax2.fill_between(range(len(dd)), dd, 0, color=_RED, alpha=0.30, label="Drawdown")
    ax2.plot(range(len(dd)), dd, color=_RED, linewidth=0.8, alpha=0.6)
    ax2.tick_params(colors=_GREY, labelsize=8)
    ax2.yaxis.label.set_color(_RED)
    ax2.set_ylabel("Drawdown ($)", fontsize=8, color=_RED)
    for spine in ax2.spines.values():
        spine.set_edgecolor("#2d3348")

    # Label trade indices as x-ticks (every 10th trade)
    n = len(cum)
    step = max(1, n // 10)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([str(i + 1) for i in range(0, n, step)], fontsize=7)
    ax.set_xlabel("Trade #", fontsize=8)
    ax.set_ylabel("Cumulative P&L ($)", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # Legend
    handles = [
        Patch(color=_ACCENT, label="Cumulative P&L"),
        Patch(color=_RED, alpha=0.5, label="Drawdown"),
    ]
    ax.legend(handles=handles, fontsize=8, facecolor=_BG, labelcolor=_TEXT,
              edgecolor="#2d3348", loc="upper left")


def _plot_trade_bars(ax, trades, pnls):
    ax.set_title("Per-Trade P&L ($)", fontsize=10, pad=6)
    colors = [_GREEN if p > 0 else _RED for p in pnls]
    x = np.arange(len(pnls))
    ax.bar(x, pnls, color=colors, width=0.8, zorder=2)
    ax.axhline(0, color=_GREY, linewidth=0.6, linestyle="--", alpha=0.6)
    ax.set_xlabel("Trade #", fontsize=8)
    ax.set_ylabel("P&L ($)", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))

    # Tick every 10th trade
    n = len(pnls)
    step = max(1, n // 8)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([str(i + 1) for i in range(0, n, step)], fontsize=7)

    legend_patches = [
        Patch(color=_GREEN, label="Win"),
        Patch(color=_RED,   label="Loss"),
    ]
    ax.legend(handles=legend_patches, fontsize=8, facecolor=_BG, labelcolor=_TEXT,
              edgecolor="#2d3348", loc="upper right")


def _plot_stats(ax, m):
    ax.set_title("Summary", fontsize=10, pad=6)
    ax.axis("off")

    pf = m["profit_factor"]
    pf_str = f"{pf:.2f}" if pf != "inf" else "∞"

    lines = [
        ("Trades",         f"{m['num_trades']}"),
        ("Trades / day",   f"{m['trades_per_day']:.2f}"),
        ("Win rate",       f"{m['win_rate_pct']:.1f}%"),
        ("Avg R",          f"{m['avg_r']:.3f}"),
        ("Expectancy",     f"${m['expectancy_usd']:,.2f}"),
        ("Net P&L",        f"${m['net_pnl_usd']:,.2f}"),
        ("Gross profit",   f"${m['gross_profit_usd']:,.2f}"),
        ("Gross loss",     f"${m['gross_loss_usd']:,.2f}"),
        ("Profit factor",  pf_str),
        ("Max drawdown",   f"${m['max_drawdown_usd']:,.2f}"),
    ]

    y = 0.95
    for label, value in lines:
        color = _GREEN if (label == "Net P&L" and m["net_pnl_usd"] > 0) else \
                _RED   if (label == "Net P&L" and m["net_pnl_usd"] < 0) else _TEXT
        ax.text(0.04, y, label, transform=ax.transAxes,
                fontsize=8.5, color=_GREY, va="top")
        ax.text(0.96, y, value, transform=ax.transAxes,
                fontsize=8.5, color=color, va="top", ha="right", fontweight="bold")
        y -= 0.092

    ax.plot([0, 1], [0.01, 0.01], color="#2d3348", linewidth=1,
            transform=ax.transAxes, clip_on=False)


def _plot_r_histogram(ax, rs):
    ax.set_title("R-Multiple Distribution", fontsize=10, pad=6)
    bins = np.linspace(min(rs) - 0.5, max(rs) + 0.5, 20)
    wins  = rs[rs > 0]
    loss  = rs[rs <= 0]
    if len(wins):
        ax.hist(wins, bins=bins, color=_GREEN, alpha=0.85, label="Win")
    if len(loss):
        ax.hist(loss, bins=bins, color=_RED,   alpha=0.85, label="Loss")
    ax.axvline(0, color=_GREY, linewidth=0.8, linestyle="--")
    ax.axvline(float(rs.mean()), color=_ACCENT, linewidth=1.2,
               linestyle="--", label=f"Mean {rs.mean():.2f}R")
    ax.set_xlabel("R-Multiple", fontsize=8)
    ax.set_ylabel("Count", fontsize=8)
    ax.legend(fontsize=7, facecolor=_BG, labelcolor=_TEXT, edgecolor="#2d3348")


def _plot_monthly(ax, monthly: pd.Series):
    ax.set_title("Monthly P&L ($)", fontsize=10, pad=6)
    if monthly.empty:
        ax.text(0.5, 0.5, "Not enough data", ha="center", va="center",
                color=_GREY, transform=ax.transAxes)
        return

    colors = [_GREEN if v > 0 else _RED for v in monthly.values]
    ax.bar(range(len(monthly)), monthly.values, color=colors, width=0.7, zorder=2)
    ax.axhline(0, color=_GREY, linewidth=0.6, linestyle="--", alpha=0.6)
    ax.set_xticks(range(len(monthly)))
    ax.set_xticklabels(
        [str(m) for m in monthly.index],
        rotation=45, ha="right", fontsize=7,
    )
    ax.set_ylabel("P&L ($)", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"${v:,.0f}"))


def _plot_exit_pie(ax, exit_breakdown: dict):
    ax.set_title("Exit Breakdown", fontsize=10, pad=6)
    labels = list(exit_breakdown.keys())
    sizes  = list(exit_breakdown.values())
    palette = {"target": _GREEN, "stop": _RED, "time_exit": _ACCENT}
    colors  = [palette.get(l, _GREY) for l in labels]
    pretty  = {"target": "Target", "stop": "Stop loss", "time_exit": "Time exit"}
    display = [pretty.get(l, l) for l in labels]

    wedges, _, autotexts = ax.pie(
        sizes, labels=display,
        colors=colors,
        autopct="%1.0f%%",
        pctdistance=0.75,
        startangle=90,
        wedgeprops={"edgecolor": _BG, "linewidth": 1.5},
        textprops={"color": _TEXT, "fontsize": 7},
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color(_BG)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _monthly_pnl(trades: List[Trade]) -> pd.Series:
    rows = [
        {"ym": t.exit_time.strftime("%Y-%m"), "pnl": t.pnl_dollars}
        for t in trades
        if t.exit_time is not None
    ]
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    return df.groupby("ym")["pnl"].sum().sort_index()
