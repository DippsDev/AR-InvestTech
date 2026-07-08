import logging
import os
import config

def setup_logger():
    os.makedirs("logs", exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log = logging.getLogger("silver_bullet_bot")
    log.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    if not log.handlers:
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setFormatter(formatter)
        log.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        log.addHandler(ch)

    return log

logger = setup_logger()
