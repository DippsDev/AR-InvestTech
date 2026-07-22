"""
AR Investments — Silver Bullet Bot
Strategy: ICT Silver Bullet + Trendline, each run concurrently across their
          own top-3 symbols (see multi_symbol_targets.py) rather than a
          single shared US30 instrument.
Risk    : SB_RISK_PCT / TL_RISK_PCT each divided evenly across all running
          instances, so total account risk stays roughly what one pair used
          to risk on US30 alone.
"""
import time
from dataclasses import replace as _dc_replace

import config
from silver_bullet.config import SilverBulletConfig
from silver_bullet.live_adapter import SilverBulletLiveAdapter
from trendline.config import TrendlineConfig
from trendline.live_adapter import TrendlineLiveAdapter
from multi_symbol_targets import SB_TARGETS, TL_TARGETS
from src.data_collector import (
    connect_mt5,
    disconnect_mt5,
    get_account_info,
)
from src.logger import logger


class SilverBulletBot:
    def __init__(self, gui_mode: bool = False):
        base_cfg = SilverBulletConfig()
        if config.SB_AGGRESSIVE:
            base_cfg.one_trade_per_window = False
            base_cfg.fvg_min_points = 3.0
            base_cfg.min_risk_points = 2.0
            # London session windows (03:00-05:00 ET) plus an early-afternoon
            # NY window (13:30-14:30 ET), on top of the core 10:00-12:00 pair.
            # Backtested combination (see 3y US30 M5 backtest): 97 trades vs
            # 67 baseline, win rate 55.7% vs 52.2%, profit factor 2.55 vs 2.60
            # — meaningfully more frequent for almost no edge cost.
            base_cfg.windows = [
                ("03:00", "04:00"), ("04:00", "05:00"),
                ("10:00", "11:00"), ("11:00", "12:00"),
                ("13:30", "14:30"),
            ]
        if config.SB_OFF_HOURS:
            base_cfg.off_hours_trading = True
        # Respect the SB_NEWS env toggle — when True, no new trades on high-impact news days.
        base_cfg.skip_news_days = config.SB_NEWS
        # Silver Bullet defaults to limit orders for better entry prices.
        # Market-order mode is only enabled for the explicit sweep-entry demo mode.
        if config.SB_SWEEP_ENTRY:
            base_cfg.sweep_entry_mode = True
            base_cfg.use_market_order = True  # sweep entry always uses market orders
        self.base_cfg = base_cfg

        self.tl_enabled = config.TL_ENABLED
        base_tl_cfg = TrendlineConfig()
        base_tl_cfg.skip_news_days = config.TL_NEWS
        self.base_tl_cfg = base_tl_cfg

        # Total concurrent instances across both strategies — each instance's
        # risk % is its strategy's configured risk_pct divided by this count,
        # so running many symbols at once doesn't multiply total account risk.
        total_instances = len(SB_TARGETS) + (len(TL_TARGETS) if self.tl_enabled else 0)
        self._instance_count = max(1, total_instances)

        # symbol -> adapter, one instance per top-3 target (see
        # multi_symbol_targets.py). Each gets its own volatility-scaled
        # thresholds and its own share of the strategy's risk budget.
        self.sb_adapters: dict[str, SilverBulletLiveAdapter] = {}
        for symbol, overrides in SB_TARGETS.items():
            cfg = _dc_replace(base_cfg, symbol=symbol, **overrides)
            risk_share = config.SB_RISK_PCT / self._instance_count
            self.sb_adapters[symbol] = SilverBulletLiveAdapter(
                cfg, symbol=symbol, risk_pct_override=risk_share
            )

        self.tl_adapters: dict[str, TrendlineLiveAdapter] = {}
        if self.tl_enabled:
            for symbol, overrides in TL_TARGETS.items():
                cfg = _dc_replace(base_tl_cfg, symbol=symbol, **overrides)
                risk_share = config.TL_RISK_PCT / self._instance_count
                self.tl_adapters[symbol] = TrendlineLiveAdapter(
                    cfg, symbol=symbol, risk_pct_override=risk_share
                )

        self.running = False
        self._gui_mode = gui_mode  # when True, bridge owns MT5 — skip disconnect on shutdown

        # News Analyst (see news_analyst.py) is US30-specific shadow-mode
        # commentary and isn't wired to any of the multi-symbol targets —
        # not called from run() below.

    def initialize(self) -> bool:
        logger.info("=" * 60)
        logger.info("  AR Investments Bot — Multi-Symbol Starting Up")
        logger.info("=" * 60)

        if not connect_mt5():
            return False

        account = get_account_info()
        if account:
            logger.info(
                f"Account | Balance: ${account['balance']:.2f} | "
                f"Equity: ${account['equity']:.2f}"
            )

        import MetaTrader5 as mt5

        # Verify every configured symbol actually exists on this broker
        # before trading it — drop (not abort on) any that don't resolve.
        for symbol in list(self.sb_adapters):
            if mt5.symbol_info(symbol) is None:
                logger.error(f"[SB] Symbol {symbol} not found on this broker — dropping instance")
                del self.sb_adapters[symbol]
            else:
                self._log_connection_diagnostics("SB", symbol)

        for symbol in list(self.tl_adapters):
            if mt5.symbol_info(symbol) is None:
                logger.error(f"[TL] Symbol {symbol} not found on this broker — dropping instance")
                del self.tl_adapters[symbol]
            else:
                self._log_connection_diagnostics("TL", symbol)

        if not self.sb_adapters and not self.tl_adapters:
            logger.error("No configured symbols resolved on this broker — nothing to trade")
            return False

        # Dashboard (bridge.py) reads config.SB_SYMBOL/TL_SYMBOL for its price
        # ticker and heatmap tile — display-only now; trading itself iterates
        # self.sb_adapters/self.tl_adapters, not these globals.
        if self.sb_adapters:
            config.SB_SYMBOL = next(iter(self.sb_adapters))
        if self.tl_adapters:
            config.TL_SYMBOL = next(iter(self.tl_adapters))

        self.running = True
        sb_syms = ", ".join(self.sb_adapters) or "(none)"
        tl_syms = ", ".join(self.tl_adapters) or "(none)"
        logger.info(
            f"Bot ready | SB symbols: {sb_syms} | TL symbols: {tl_syms} | "
            f"risk split across {self._instance_count} instances"
        )
        return True

    def _log_connection_diagnostics(self, label: str, symbol: str) -> None:
        """Log the symbol/spread details worth knowing at a glance whenever
        the bot starts — the same things worth checking by hand when
        diagnosing "is this actually connected and able to trade"."""
        try:
            import MetaTrader5 as mt5
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if info and tick:
                spread_pts = (tick.ask - tick.bid) / info.point if info.point else 0
                logger.info(
                    f"[{label}] Symbol | {symbol} | trade_mode={info.trade_mode} (4=full) | "
                    f"volume_min={info.volume_min} volume_max={info.volume_max} "
                    f"step={info.volume_step} | digits={info.digits} | "
                    f"spread={spread_pts:.1f}pts | bid={tick.bid} ask={tick.ask}"
                )
        except Exception as exc:
            logger.warning(f"[{label}] Connection diagnostics unavailable for {symbol}: {exc}")

    def run(self) -> None:
        if not self.initialize():
            logger.error("Initialization failed — exiting")
            return

        try:
            while self.running:
                # Adaptive daily-trade floor: share every instance's real,
                # MT5-history-derived trade count with all the others so each
                # can tell whether the combined total is behind pace for
                # today (see SilverBulletLiveAdapter._boost_active).
                combined_trades = sum(a._daily_trades for a in self.sb_adapters.values())
                combined_trades += sum(a._daily_trades for a in self.tl_adapters.values())
                for a in self.sb_adapters.values():
                    a.combined_daily_trades = combined_trades
                for a in self.tl_adapters.values():
                    a.combined_daily_trades = combined_trades

                for symbol, adapter in self.sb_adapters.items():
                    try:
                        adapter.cycle(symbol)
                    except Exception as exc:
                        logger.error(f"[SB] Error in {symbol} cycle: {exc}", exc_info=True)
                for symbol, adapter in self.tl_adapters.items():
                    try:
                        adapter.cycle(symbol)
                    except Exception as exc:
                        logger.error(f"[TL] Error in {symbol} cycle: {exc}", exc_info=True)
                # 5-second sleep with a 1-second heartbeat so the log shows
                # the bot is alive at every second.
                for remaining in range(5, 0, -1):
                    if not self.running:
                        break
                    logger.debug(f"[Bot] Heartbeat | next cycle in {remaining}s")
                    time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt — shutting down")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        logger.info("Closing positions and disconnecting...")
        for symbol, adapter in self.sb_adapters.items():
            adapter.shutdown(symbol)
        for symbol, adapter in self.tl_adapters.items():
            adapter.shutdown(symbol)
        if not self._gui_mode:
            disconnect_mt5()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    SilverBulletBot().run()
