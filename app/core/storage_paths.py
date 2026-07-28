"""Storage directory initialization for market data infrastructure."""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def ensure_storage_directories(settings: Settings | None = None) -> dict[str, Path]:
    """Create required storage directories if they do not exist.

    Ensures::

        backend/data/
        backend/data/metadata.db   (parent dir only; DB created by SQLAlchemy)
        backend/data/ohlcv/        (empty initially)
        backend/data/logs/

    Args:
        settings: Optional settings override.

    Returns:
        Mapping of logical names to resolved directory paths.
    """
    cfg = settings or get_settings()
    data_root = cfg.data_root
    ohlcv_dir = Path(cfg.parquet_storage_dir)
    logs_dir = Path(cfg.log_directory)

    data_root.mkdir(parents=True, exist_ok=True)
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Storage directories ready (data_root=%s, ohlcv=%s, logs=%s)",
        data_root,
        ohlcv_dir,
        logs_dir,
    )
    return {
        "data_root": data_root,
        "ohlcv": ohlcv_dir,
        "logs": logs_dir,
    }
