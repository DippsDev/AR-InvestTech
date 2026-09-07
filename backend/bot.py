"""
AR Investments — Silver Bullet Bot
Strategy: ICT Silver Bullet + Trendline + Mutanabby, each run concurrently
          across their own top-3 symbols (see multi_symbol_targets.py) rather
          than a single shared US30 instrument.
Risk    : SB_RISK_PCT / TL_RISK_PCT each divided evenly across all running
          SB+TL instances, so total account risk stays roughly what one pair
          used to risk on US30 alone. MB_RISK_PCT is divided across MB
          instances ONLY — see _instance_count below for why.
"""
import time
from dataclasses import replace as _dc_replace

import config
from silver_bullet.config import SilverBulletConfig
from silver_bullet.live_adapter import SilverBulletLiveAdapter
from trendline.config import TrendlineConfig
from trendline.live_adapter import TrendlineLiveAdapter
from mutanabby.config import MutanabbyConfig
from mutanabby.live_adapter import MutanabbyLiveAdapter
from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS
from src import mt5_cache
from src.aggressive_stops import ATR_RISK_MULT, STOP_BUFFER_MULT, apply_aggressive_stops
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
            # Wider stops / later breakeven are applied after per-symbol
            # overrides below — SB_TARGETS would clobber a buffer change here.
        if config.SB_OFF_HOURS:
            base_cfg.off_hours_trading = True
        # Respect the SB_NEWS env toggle — when True, no new trades on high-impact news days.
        base_cfg.skip_news_days = config.SB_NEWS
        base_cfg.min_stop_spread_mult = config.SB_MIN_STOP_SPREAD_MULT
        # Silver Bullet defaults to limit orders for better entry prices.
        # Market-order mode is only enabled for the explicit sweep-entry demo mode.
        if config.SB_SWEEP_ENTRY:
            base_cfg.sweep_entry_mode = True
            base_cfg.use_market_order = True  # sweep entry always uses market orders
        self.base_cfg = base_cfg

        self.tl_enabled = config.TL_ENABLED
        base_tl_cfg = TrendlineConfig()
        base_tl_cfg.skip_news_days = config.TL_NEWS
        base_tl_cfg.min_stop_spread_mult = config.TL_MIN_STOP_SPREAD_MULT
        self.base_tl_cfg = base_tl_cfg

        self.mb_enabled = config.MB_ENABLED
        base_mb_cfg = MutanabbyConfig()
        base_mb_cfg.skip_news_days = config.MB_NEWS
        self.base_mb_cfg = base_mb_cfg

        # Total concurrent SB+TL instances — each instance's risk % is its
        # strategy's configured risk_pct divided by this count, so running many
        # symbols at once doesn't multiply total account risk.
        #
        # Mutanabby is deliberately EXCLUDED from this divisor and gets its own
        # (below). Including it would silently shrink every SB and TL position:
        # with 2 SB + 3 TL the divisor is 5, and adding 3 MB instances would
        # push it to 8, cutting SB/TL per-instance risk. MB's
        # evidence is much weaker than theirs (see mutanabby/README.md), so it
        # funds itself out of MB_RISK_PCT rather than out of their budget.
        # Enabling MB therefore ADDS at most MB_RISK_PCT of account risk — keep
        # that number small.
        total_instances = len(SB_TARGETS) + (len(TL_TARGETS) if self.tl_enabled else 0)
        self._instance_count = max(1, total_instances)
        self._mb_instance_count = max(1, len(MB_TARGETS)) if self.mb_enabled else 1

        # symbol -> adapter, one instance per live target (see
        # multi_symbol_targets.py). Each gets its own volatility-scaled
        # thresholds and its own share of the strategy's risk budget.
        self.sb_adapters: dict[str, SilverBulletLiveAdapter] = {}
        for symbol, overrides in SB_TARGETS.items():
            cfg = _dc_replace(base_cfg, symbol=symbol, **overrides)
            if config.SB_AGGRESSIVE:
                cfg = apply_aggressive_stops(cfg)
            risk_share = config.SB_RISK_PCT / self._instance_count
            self.sb_adapters[symbol] = SilverBulletLiveAdapter(
                cfg, symbol=symbol, risk_pct_override=risk_share
            )

        self.tl_adapters: dict[str, TrendlineLiveAdapter] = {}
        if self.tl_enabled:
            for symbol, overrides in TL_TARGETS.items():
                cfg = _dc_replace(base_tl_cfg, symbol=symbol, **overrides)
                if config.SB_AGGRESSIVE:
                    cfg = apply_aggressive_stops(cfg)
                risk_share = config.TL_RISK_PCT / self._instance_count
                self.tl_adapters[symbol] = TrendlineLiveAdapter(
                    cfg, symbol=symbol, risk_pct_override=risk_share
                )

        self.mb_adapters: dict[str, MutanabbyLiveAdapter] = {}
        if self.mb_enabled:
            for symbol, overrides in MB_TARGETS.items():
                cfg = _dc_replace(base_mb_cfg, symbol=symbol, **overrides)
                if config.SB_AGGRESSIVE:
                    cfg = apply_aggressive_stops(cfg)
                risk_share = config.MB_RISK_PCT / self._mb_instance_count
                self.mb_adapters[symbol] = MutanabbyLiveAdapter(
                    cfg, symbol=symbol, risk_pct_override=risk_share
                )

        self.running = False
        self._gui_mode = gui_mode  # when True, bridge owns MT5 — skip disconnect on shutdown
        self._tick_count = 0       # loop ticks, for the periodic MT5 snapshot log

        # News Analyst — daily bias for the live book (see news_analyst.py).
        # Date is the last NY day we already attempted the Claude call.
        self._news_analyst_date: str | None = None

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

        for symbol in list(self.mb_adapters):
            if mt5.symbol_info(symbol) is None:
                logger.error(f"[MB] Symbol {symbol} not found on this broker — dropping instance")
                del self.mb_adapters[symbol]
            else:
                self._log_connection_diagnostics("MB", symbol)

        if not self.sb_adapters and not self.tl_adapters and not self.mb_adapters:
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
        mb_syms = ", ".join(self.mb_adapters) or "(none)"
        logger.info(
            f"Bot ready | SB symbols: {sb_syms} | TL symbols: {tl_syms} | "
            f"MB symbols: {mb_syms} | SB/TL risk split across "
            f"{self._instance_count} instances"
        )
        if config.SB_AGGRESSIVE:
            logger.info(
                f"[Bot] Aggressive wide stops | buffer x{STOP_BUFFER_MULT:g} "
                f"(SB/TL) | ATR stop x{ATR_RISK_MULT:g} (MB) | "
                f"SB breakeven/trail loosened, early-exit off | "
                f"dollar risk unchanged (smaller lots)"
            )
        if self.mb_adapters:
            logger.info(
                f"[MB] Mutanabby live | {len(self.mb_adapters)} instance(s) | "
                f"{config.MB_RISK_PCT:.2f}% risk split across them "
                f"({config.MB_RISK_PCT / self._mb_instance_count:.3f}% each) | "
                f"separate budget — SB/TL sizing unchanged"
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

    def _live_symbols(self) -> list[str]:
        return list(dict.fromkeys([
            *self.sb_adapters,
            *self.tl_adapters,
            *self.mb_adapters,
        ]))

    def _maybe_run_news_analyst(self) -> None:
        """Shadow-mode: once per NY trading day, ask Claude for a directional
        bias on every live symbol and log/persist it for later evaluation.
        Also grades any prior day's calls against what each price actually
        did. Failures here must never take down the bot loop."""
        if not (config.NEWS_ANALYST_ENABLED and config.ANTHROPIC_API_KEY):
            return

        from datetime import datetime
        from zoneinfo import ZoneInfo

        today_ny = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        if today_ny == self._news_analyst_date:
            return

        symbols = self._live_symbols()
        if not symbols:
            return

        try:
            import news_analyst

            prices: dict[str, float] = {}
            for symbol in symbols:
                tick = mt5_cache.symbol_info_tick(symbol)
                if tick is None:
                    logger.info(f"[Analyst] No tick data for {symbol} — skipping today's bias call")
                    return
                prices[symbol] = (tick.bid + tick.ask) / 2

            if not news_analyst.has_called_today(today_ny, symbols):
                calls = news_analyst.get_daily_bias(prices)
                for call in calls:
                    news_analyst.record_bias(call)
                    logger.info(
                        f"[Analyst] Bias {call.symbol} {call.direction.upper()} "
                        f"(confidence {call.confidence:.2f}) | {call.reasoning[:200]}"
                    )

            self._news_analyst_date = today_ny

            graded = news_analyst.grade_pending_calls(prices, current_date=today_ny)
            for g in graded:
                outcome = "correct" if g.graded else "incorrect"
                logger.info(
                    f"[Analyst] Graded {g.date} {g.symbol} | called {g.direction} | "
                    f"actual {g.actual_direction} | {outcome}"
                )
        except Exception as exc:
            self._news_analyst_date = today_ny
            logger.warning(f"[Analyst] Daily bias check failed: {exc}")

    def run(self) -> None:
        if not self.initialize():
            logger.error("Initialization failed — exiting")
            return

        try:
            while self.running:
                # Open a new MT5 snapshot window. Every adapter below reads the
                # account, today's deals, open positions and per-symbol
                # info/ticks through src/mt5_cache, so each of those costs one
                # IPC round-trip per loop tick instead of one per adapter.
                mt5_cache.begin_tick()
                self._maybe_run_news_analyst()

                # Adaptive daily-trade floor: share every instance's real,
                # MT5-history-derived trade count with all the others so each
                # can tell whether the combined total is behind pace for
                # today (see SilverBulletLiveAdapter._boost_active).
                # MB is included in the combined count so the floor reflects
                # real activity, but MB itself has no boost mode to trigger —
                # its only entry knob is `sensitivity`, and changing that
                # produces different signals rather than admitting marginal
                # ones (see mutanabby/live_adapter.py).
                combined_trades = sum(a._daily_trades for a in self.sb_adapters.values())
                combined_trades += sum(a._daily_trades for a in self.tl_adapters.values())
                combined_trades += sum(a._daily_trades for a in self.mb_adapters.values())
                for a in self.sb_adapters.values():
                    a.combined_daily_trades = combined_trades
                for a in self.tl_adapters.values():
                    a.combined_daily_trades = combined_trades
                for a in self.mb_adapters.values():
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
                for symbol, adapter in self.mb_adapters.items():
                    try:
                        adapter.cycle(symbol)
                    except Exception as exc:
                        logger.error(f"[MB] Error in {symbol} cycle: {exc}", exc_info=True)
                # Periodic snapshot-efficiency line (every 60 ticks ~= 5 min):
                # how many MT5 round-trips the tick actually cost versus how
                # many reads were served from the shared snapshot.
                self._tick_count += 1
                if self._tick_count % 60 == 0:
                    fetches, hits = mt5_cache.tick_stats()
                    logger.info(
                        f"[Bot] MT5 snapshot | {fetches} round-trip(s), {hits} "
                        f"served from cache this tick | {len(self.sb_adapters)} SB + "
                        f"{len(self.tl_adapters)} TL + {len(self.mb_adapters)} MB adapters"
                    )

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
        for symbol, adapter in self.mb_adapters.items():
            adapter.shutdown(symbol)
        if not self._gui_mode:
            disconnect_mt5()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    SilverBulletBot().run()
