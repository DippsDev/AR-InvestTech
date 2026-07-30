import logging

import config

def setup_logger():
    # No makedirs here: config.LOG_FILE already lives under paths.log_dir(),
    # which creates it. The old `os.makedirs("logs")` was relative to the
    # cwd, so under a Windows service (or the tray app, which chdirs) it
    # created a stray directory somewhere else and left the real log dir
    # missing.
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
