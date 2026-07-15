"""
AR Investments — Silver Bullet Bot
Strategy: ICT Silver Bullet on US30 (Dow Jones), M5 candles
Active  : NY 10:00–12:00 only
Risk    : 1% per trade, stop behind swept extreme, 3R target
"""
import time

import config
from silver_bullet.config import SilverBulletConfig
from silver_bullet.live_adapter import SilverBulletLiveAdapter
from trendline.config import TrendlineConfig
from trendline.live_adapter import TrendlineLiveAdapter
from src.data_collector import (
    connect_mt5,
    disconnect_mt5,
    find_us30_symbol,
    get_account_info,
)
from src.logger import logger


class SilverBulletBot:
    def __init__(self, gui_mode: bool = False):
        cfg = SilverBulletConfig()
        if config.SB_AGGRESSIVE:
            cfg.one_trade_per_window = False
            cfg.fvg_min_points = 3.0
            cfg.min_risk_points = 2.0
            # London session windows (03:00-05:00 ET) plus an early-afternoon
            # NY window (13:30-14:30 ET), on top of the core 10:00-12:00 pair.
            # Backtested combination (see 3y US30 M5 backtest): 97 trades vs
            # 67 baseline, win rate 55.7% vs 52.2%, profit factor 2.55 vs 2.60
            # — meaningfully more frequent for almost no edge cost.
            cfg.windows = [
                ("03:00", "04:00"), ("04:00", "05:00"),
                ("10:00", "11:00"), ("11:00", "12:00"),
                ("13:30", "14:30"),
            ]
        if config.SB_OFF_HOURS:
            cfg.off_hours_trading = True
        # Respect the SB_NEWS env toggle — when True, no new trades on high-impact news days.
        cfg.skip_news_days = config.SB_NEWS
        # Silver Bullet defaults to limit orders for better entry prices.
        # Market-order mode is only enabled for the explicit sweep-entry demo mode.
        if config.SB_SWEEP_ENTRY:
            cfg.sweep_entry_mode = True
            cfg.use_market_order = True  # sweep entry always uses market orders
        self.cfg = cfg
        self._symbol: str | None = None
        self.adapter = SilverBulletLiveAdapter(cfg, symbol=None)
        self.running = False
        self._gui_mode = gui_mode  # when True, bridge owns MT5 — skip disconnect on shutdown

        # Trendline strategy — independent second strategy, off by default.
        # Fully gated so that when TL_ENABLED is false (the default), every
        # branch below is skipped and behavior is identical to before this
        # strategy existed.
        self.tl_enabled = config.TL_ENABLED
        self.tl_symbol: str | None = None
        self.tl_adapter: TrendlineLiveAdapter | None = None
        if self.tl_enabled:
            tl_cfg = TrendlineConfig()
            tl_cfg.skip_news_days = config.TL_NEWS
            self.tl_adapter = TrendlineLiveAdapter(tl_cfg, symbol=None)

        # News Analyst — shadow-mode daily bias (see news_analyst.py).
        # Purely observational; never gates or sizes real trades.
        self._news_analyst_date: str | None = None

    def initialize(self) -> bool:
        logger.info("=" * 60)
        logger.info("  Silver Bullet Bot (US30) — Starting Up")
        logger.info("=" * 60)

        if not connect_mt5():
            return False

        account = get_account_info()
        if account:
            logger.info(
                f"Account | Balance: ${account['balance']:.2f} | "
                f"Equity: ${account['equity']:.2f}"
            )

        resolved = find_us30_symbol()
        if resolved:
            config.SB_SYMBOL = resolved
            self._symbol = resolved
            self.adapter._symbol = resolved
        else:
            logger.error("US30 symbol not found on this broker — set SB_SYMBOL in .env")
            return False

        self._log_connection_diagnostics(resolved)

        if self.tl_enabled:
            # Trendline now trades the SAME instrument as Silver Bullet (US30),
            # not a separate EURUSD symbol — reuse the already-resolved symbol
            # rather than doing an independent broker lookup, so there is no
            # way for the two strategies to end up on different instruments.
            config.TL_SYMBOL = resolved
            self.tl_symbol = resolved
            self.tl_adapter._symbol = resolved
            logger.info(f"Trendline strategy enabled | Symbol: {resolved}")

        self.running = True
        windows_str = ", ".join(f"{s}-{e} ET" for s, e in self.cfg.windows)
        order_type = "MARKET" if self.cfg.use_market_order else "LIMIT"
        news_mode = "SKIP NEWS" if self.cfg.skip_news_days else "NEWS ALLOWED"
        logger.info(f"Bot ready | Symbol: {self._symbol} | Windows: {windows_str} | Order: {order_type} | {news_mode}")
        return True

    def _log_connection_diagnostics(self, symbol: str) -> None:
        """Log the account/symbol/terminal details worth knowing at a glance
        whenever the bot starts — the same things worth checking by hand
        when diagnosing "is this actually connected and able to trade"."""
        try:
            import MetaTrader5 as mt5
            acc = mt5.account_info()
            if acc:
                logger.info(
                    f"Account | Login: {acc.login} | Server: {acc.server} | "
                    f"Leverage: 1:{acc.leverage} | Currency: {acc.currency} | "
                    f"AlgoTrading allowed: {acc.trade_expert} | Trade allowed: {acc.trade_allowed}"
                )
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            if info and tick:
                spread_pts = (tick.ask - tick.bid) / info.point if info.point else 0
                logger.info(
                    f"Symbol | {symbol} | trade_mode={info.trade_mode} (4=full) | "
                    f"volume_min={info.volume_min} volume_max={info.volume_max} "
                    f"step={info.volume_step} | digits={info.digits} | "
                    f"spread={spread_pts:.1f}pts | bid={tick.bid} ask={tick.ask}"
                )
            logger.info(f"Terminal | Path: {config.MT5_PATH or '(auto-detected)'}")
        except Exception as exc:
            logger.warning(f"Connection diagnostics unavailable: {exc}")

    def _maybe_run_news_analyst(self, symbol: str) -> None:
        """Shadow-mode: once per NY trading day, ask Claude for a US30
        directional bias and log/persist it for later evaluation. Also
        grades any prior day's call against what price actually did.
        Never gates or sizes real trades — failures here must never take
        down the bot loop."""
        if not (config.NEWS_ANALYST_ENABLED and config.ANTHROPIC_API_KEY):
            return

        from datetime import datetime
        from zoneinfo import ZoneInfo

        today_ny = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if today_ny == self._news_analyst_date:
            return
        self._news_analyst_date = today_ny

        try:
            import MetaTrader5 as mt5
            import news_analyst

            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                logger.warning("[Analyst] No tick data — skipping today's bias call")
                return
            price = (tick.bid + tick.ask) / 2

            if not news_analyst.has_called_today(today_ny):
                call = news_analyst.get_daily_bias(reference_price=price)
                news_analyst.record_bias(call)
                logger.info(
                    f"[Analyst] Bias {call.direction.upper()} "
                    f"(confidence {call.confidence:.2f}) | {call.reasoning[:200]}"
                )

            graded = news_analyst.grade_pending_calls(current_price=price, current_date=today_ny)
            for g in graded:
                outcome = "correct" if g.graded else "incorrect"
                logger.info(
                    f"[Analyst] Graded {g.date} | called {g.direction} | "
                    f"actual {g.actual_direction} | {outcome}"
                )
        except Exception as exc:
            logger.warning(f"[Analyst] Daily bias check failed: {exc}")

    def run(self) -> None:
        if not self.initialize():
            logger.error("Initialization failed — exiting")
            return

        symbol = self._symbol or config.SB_SYMBOL
        try:
            while self.running:
                self._maybe_run_news_analyst(symbol)

                # Adaptive daily-trade floor: share each strategy's real,
                # MT5-history-derived trade count with the other so both can
                # tell whether the combined total is behind pace for today
                # (see SilverBulletLiveAdapter._boost_active).
                combined_trades = self.adapter._daily_trades + (
                    self.tl_adapter._daily_trades if self.tl_enabled else 0
                )
                self.adapter.combined_daily_trades = combined_trades
                if self.tl_enabled:
                    self.tl_adapter.combined_daily_trades = combined_trades

                try:
                    self.adapter.cycle(symbol)
                except Exception as exc:
                    logger.error(f"[SB] Error in cycle: {exc}", exc_info=True)
                if self.tl_enabled and self.tl_symbol:
                    try:
                        self.tl_adapter.cycle(self.tl_symbol)
                    except Exception as exc:
                        logger.error(f"[TL] Error in cycle: {exc}", exc_info=True)
                # 5-second sleep with a 1-second heartbeat so the log shows
                # the bot is alive at every second.
                for remaining in range(5, 0, -1):
                    if not self.running:
                        break
                    logger.debug(f"[SB] Heartbeat | next cycle in {remaining}s")
                    time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt — shutting down")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        logger.info("Closing positions and disconnecting...")
        self.adapter.shutdown(self._symbol or config.SB_SYMBOL)
        if self.tl_enabled and self.tl_symbol:
            self.tl_adapter.shutdown(self.tl_symbol)
        if not self._gui_mode:
            disconnect_mt5()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    SilverBulletBot().run()
