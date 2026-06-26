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
from src.data_collector import connect_mt5, disconnect_mt5, find_us30_symbol, get_account_info
from src.logger import logger


class SilverBulletBot:
    def __init__(self, gui_mode: bool = False):
        cfg = SilverBulletConfig()
        if config.SB_AGGRESSIVE:
            cfg.one_trade_per_window = False
            cfg.fvg_min_points = 3.0
            cfg.min_risk_points = 2.0
            # Prepend London session windows (03:00–05:00 ET) for extra setups
            cfg.windows = [
                ("03:00", "04:00"), ("04:00", "05:00"),
                ("10:00", "11:00"), ("11:00", "12:00"), ("13:30", "14:30"),
            ]
        if config.SB_OFF_HOURS:
            cfg.off_hours_trading = True
        self.adapter = SilverBulletLiveAdapter(cfg)
        self.running = False
        self._gui_mode = gui_mode  # when True, bridge owns MT5 — skip disconnect on shutdown

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
        else:
            logger.error("US30 symbol not found on this broker — set SB_SYMBOL in .env")
            return False

        self.running = True
        logger.info(f"Bot ready | Symbol: {config.SB_SYMBOL} | Window: NY 10:00–12:00")
        return True

    def run(self) -> None:
        if not self.initialize():
            logger.error("Initialization failed — exiting")
            return

        try:
            while self.running:
                try:
                    self.adapter.cycle(config.SB_SYMBOL)
                except Exception as exc:
                    logger.error(f"[SB] Error in cycle: {exc}", exc_info=True)
                time.sleep(30)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt — shutting down")
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        logger.info("Closing positions and disconnecting...")
        self.adapter.shutdown(config.SB_SYMBOL)
        if not self._gui_mode:
            disconnect_mt5()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    SilverBulletBot().run()
