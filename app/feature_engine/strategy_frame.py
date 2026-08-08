"""Build strategy-ready frames by joining OHLCV with indicator features.

``FeaturePipeline`` persists indicator columns plus ``date`` only (see
``tests/test_ema_trend_strategy.py``). Strategies need raw OHLCV as well, so
callers must merge before ``StrategyRunner.run``.

Indicators are **not** computed inside strategy.prepare() — they come from the
Feature Engine modules (``compute_trend_features``, etc.). When parquet only
has OHLCV, call ``ensure_strategy_indicators`` before running strategies.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.market_data.utils.symbols import parquet_basename

OHLCV_REQUIRED: frozenset[str] = frozenset(
    {"date", "open", "high", "low", "close", "volume"},
)

# Columns commonly required by EMA trend (raw + professional) and peers.
STRATEGY_INDICATOR_COLUMNS: frozenset[str] = frozenset(
    {
        "ema_9",
        "ema_20",
        "ema_21",
        "ema_50",
        "ema_200",
        "adx_14",
        "atr_14",
        "rsi_14",
        "volume_sma_20",
        "relative_volume_20",
    },
)


def features_include_ohlcv(frame: pd.DataFrame) -> bool:
    """True when ``frame`` already carries the OHLCV columns strategies need."""
    return OHLCV_REQUIRED.issubset(frame.columns)


def ensure_strategy_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach canonical Feature Engine indicators when missing.

    Reuses existing modules (same path as ``StrategyContextProvider``):
    ``compute_trend_features``, ``compute_momentum_features``,
    ``compute_volatility_features``, ``compute_volume_features``.

    Does **not** invent new formulas. No-ops when OHLCV is incomplete or all
    required indicator columns are already present.
    """
    if frame is None or frame.empty:
        return frame
    if not features_include_ohlcv(frame):
        return frame

    missing = sorted(
        column for column in STRATEGY_INDICATOR_COLUMNS if column not in frame.columns
    )
    if not missing:
        return frame

    from app.feature_engine.indicators.momentum import compute_momentum_features
    from app.feature_engine.indicators.trend import compute_trend_features
    from app.feature_engine.indicators.volatility import compute_volatility_features
    from app.feature_engine.indicators.volume import compute_volume_features

    out = frame.copy()
    needs_trend = any(
        column.startswith("ema_") or column == "adx_14" for column in missing
    )
    needs_momentum = "rsi_14" in missing
    needs_volatility = "atr_14" in missing
    needs_volume = any(
        column in {"volume_sma_20", "relative_volume_20"} for column in missing
    )

    generated: list[pd.DataFrame] = []
    if needs_trend:
        generated.append(compute_trend_features(out))
    if needs_momentum:
        generated.append(compute_momentum_features(out))
    if needs_volatility:
        generated.append(compute_volatility_features(out))
    if needs_volume:
        generated.append(compute_volume_features(out))

    for block in generated:
        for column in block.columns:
            if column not in out.columns:
                out[column] = block[column].to_numpy()
    return out


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
    *,
    ensure_indicators: bool = False,
) -> pd.DataFrame | None:
    """Load ``SYMBOL_features.parquet`` merged with ``SYMBOL.parquet`` OHLCV.

    Returns ``None`` when neither features nor OHLCV exist. If only OHLCV exists,
    returns the OHLCV frame (strategies that need indicators may still fail
    validation — callers can fall back to synthetic data or pass
    ``ensure_indicators=True`` to compute canonical Feature Engine columns).
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
        frame = features
    elif features is not None and ohlcv is not None:
        frame = merge_ohlcv_features(ohlcv, features)
    elif features is not None:
        # Indicators only — cannot satisfy strategy OHLCV requirements alone
        frame = features
    else:
        frame = ohlcv

    if ensure_indicators and frame is not None:
        frame = ensure_strategy_indicators(frame)
    return frame
