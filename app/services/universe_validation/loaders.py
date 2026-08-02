"""Feature / OHLCV loading helpers for universe validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.feature_engine.strategy_frame import (
    features_include_ohlcv,
    load_strategy_features,
)
from app.strategy_engine.symbols import attach_symbol


def load_symbol_features(
    symbol: str,
    storage_dir: Path | str,
) -> tuple[pd.DataFrame | None, str | None]:
    """Load strategy-ready features for ``symbol``.

    Returns ``(frame, error)``. On success ``error`` is ``None``.
    Requires OHLCV columns (merged from source parquet when needed).
    """
    frame = load_strategy_features(symbol, storage_dir)
    if frame is not None and features_include_ohlcv(frame):
        return attach_symbol(frame, symbol), None

    if frame is not None and not features_include_ohlcv(frame):
        return None, (
            f"{symbol}: feature file missing OHLCV and no mergeable "
            f"{symbol}.parquet found"
        )

    return None, f"{symbol}: no OHLCV parquet in {storage_dir}"


def synthetic_session_features(
    *,
    symbol: str,
    bars: int = 100,
) -> pd.DataFrame:
    """Deterministic multi-session synthetic frame for tests / dry runs."""
    sessions: list[pd.Timestamp] = []
    day = pd.Timestamp("2024-06-03 09:15")
    while len(sessions) < bars:
        for minute in range(0, 6 * 60, 15):
            sessions.append(day + pd.Timedelta(minutes=minute))
            if len(sessions) >= bars:
                break
        day = day + pd.Timedelta(days=1)
        while day.weekday() >= 5:
            day = day + pd.Timedelta(days=1)

    rows: list[dict[str, float | pd.Timestamp]] = []
    price = 100.0
    for index, ts in enumerate(sessions[:bars]):
        price = 100.0 + index * 0.25
        close = price
        rows.append(
            {
                "date": ts,
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_500 + index * 10,
                "relative_volume_20": 2.0,
                "atr_14": 1.5,
                "ema_9": close,
                "ema_20": close + 1.0,
                "ema_21": close + 1.0,
                "ema_50": close - 1.0,
                "adx_14": 30.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)
