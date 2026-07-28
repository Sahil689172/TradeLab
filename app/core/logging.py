"""Centralized logging configuration for TradeLab."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

LOG_FORMAT_CONSOLE = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)
LOG_FORMAT_JSON = (
    '{"time":"%(asctime)s","level":"%(levelname)s",'
    '"logger":"%(name)s","message":"%(message)s"}'
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(settings: Settings) -> None:
    """Configure root and application loggers.

    Args:
        settings: Application settings providing log level and format.
    """
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(settings.log_level)

    fmt = LOG_FORMAT_JSON if settings.log_format == "json" else LOG_FORMAT_CONSOLE
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=DATE_FORMAT))
    root_logger.addHandler(handler)

    # Keep noisy third-party loggers quieter unless debugging.
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(
            logging.DEBUG if settings.debug else logging.WARNING
        )

    logging.getLogger("app").setLevel(settings.log_level)
    logging.getLogger("app").debug(
        "Logging configured (level=%s, format=%s)",
        settings.log_level,
        settings.log_format,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a named logger under the ``app`` namespace.

    Args:
        name: Logger suffix (module name recommended).

    Returns:
        Configured ``logging.Logger`` instance.
    """
    if name.startswith("app."):
        return logging.getLogger(name)
    return logging.getLogger(f"app.{name}")
