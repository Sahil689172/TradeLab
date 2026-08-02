"""Build strategy-ready frames by joining OHLCV with indicator features.

``FeaturePipeline`` persists indicator columns plus ``date`` only (see
``tests/test_ema_trend_strategy.py``). Strategies need raw OHLCV as well, so
callers must merge before ``StrategyRunner.run``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.market_data.utils.symbols import parquet_basename

OHLCV_REQUIRED: frozenset[str] = frozenset(
    {"date", "open", "high", "low", "close", "volume"},
)


def features_include_ohlcv(frame: pd.DataFrame) -> bool:
    """True when ``frame`` already carries the OHLCV columns strategies need."""
    return OHLCV_REQUIRED.issubset(frame.columns)


def merge_ohlcv_features(
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
) -> pd.DataFrame:
    """Inner-join OHLCV with a feature frame on ``date``.

    Feature columns that duplicate OHLCV names (other than ``date``) are dropped
    from the feature side so OHLCV prices win.
    """
    if ohlcv is None or ohlcv.empty:
        raise ValueError("OHLCV frame must not be empty")
    if features is None or features.empty:
        raise ValueError("Feature frame must not be empty")
    if "date" not in ohlcv.columns or "date" not in features.columns:
        raise ValueError("Both OHLCV and features must contain a 'date' column")

    left = ohlcv.copy()
    right = features.copy()
    left["date"] = pd.to_datetime(left["date"])
    right["date"] = pd.to_datetime(right["date"])

    if features_include_ohlcv(right):
        # Already strategy-ready (e.g. caller pre-merged or pipeline includes OHLCV)
        return (
            right.drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

    drop_from_right = [
        column
        for column in right.columns
        if column != "date" and column in left.columns
    ]
    if drop_from_right:
        right = right.drop(columns=drop_from_right)

    merged = left.merge(right, on="date", how="inner")
    if merged.empty:
        raise ValueError("OHLCV/features merge produced an empty frame (no shared dates)")
    return (
        merged.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def load_strategy_features(
    symbol: str,
    storage_dir: Path | str,
) -> pd.DataFrame | None:
    """Load ``SYMBOL_features.parquet`` merged with ``SYMBOL.parquet`` OHLCV.

    Returns ``None`` when neither features nor OHLCV exist. If only OHLCV exists,
    returns the OHLCV frame (strategies that need indicators may still fail
    validation — callers can fall back to synthetic data).
    """
    root = Path(storage_dir)
    stem = parquet_basename(symbol)
    features_path = root / f"{stem}_features.parquet"
    ohlcv_path = root / f"{stem}.parquet"

    features: pd.DataFrame | None = None
    ohlcv: pd.DataFrame | None = None

    if features_path.exists():
        features = pd.read_parquet(features_path, engine="pyarrow")
    if ohlcv_path.exists():
        ohlcv = pd.read_parquet(ohlcv_path, engine="pyarrow")

    if features is None and ohlcv is None:
        return None
    if features is not None and features_include_ohlcv(features):
        return features
    if features is not None and ohlcv is not None:
        return merge_ohlcv_features(ohlcv, features)
    if features is not None:
        # Indicators only — cannot satisfy strategy OHLCV requirements alone
        return features
    return ohlcv
