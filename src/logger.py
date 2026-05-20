# src/logger.py
# Configures and exposes a single loguru logger for the whole project.
# Import pattern in every module:  from loguru import logger

import sys
from loguru import logger
from config.settings import LOG_DIR, LOG_LEVEL, LOG_ROTATION, LOG_RETENTION

LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()  # remove default stderr handler

logger.add(
    sys.stdout,
    level=LOG_LEVEL,
    colorize=True,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
)

logger.add(
    LOG_DIR / "poc_{time:YYYY-MM-DD}.log",
    level=LOG_LEVEL,
    rotation=LOG_ROTATION,
    retention=LOG_RETENTION,
    encoding="utf-8",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
)
