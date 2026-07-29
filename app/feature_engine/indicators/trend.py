"""Trend-following technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd

EMA_PERIODS = (9, 21, 50, 200)
SMA_PERIODS = (20, 50, 200)


def ema(series: pd.Series, period: int) -> pd.Series:
    """Return an exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """Return a simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def macd(close: pd.Series) -> pd.DataFrame:
    """Return MACD line, signal, and histogram."""
    line = ema(close, 12) - ema(close, 26)
    signal = line.ewm(span=9, adjust=False).mean()
    return pd.DataFrame(
        {
            "macd": line,
            "macd_signal": signal,
            "macd_histogram": line - signal,
        },
        index=close.index,
    )


def adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Wilder's Average Directional Index."""
    high = data["high"]
    low = data["low"]
    close = data["close"]
    previous_close = close.shift(1)

    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    average_true_range = true_range.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=data.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=data.index,
    )
    plus_di = (
        100
        * plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        / average_true_range
    )
    minus_di = (
        100
        * minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        / average_true_range
    )
    denominator = (plus_di + minus_di).replace(0, np.nan)
    directional_index = 100 * (plus_di - minus_di).abs() / denominator
    return directional_index.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def compute_trend_features(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all trend features without mutating input."""
    close = data["close"].astype("float64")
    features = pd.DataFrame(index=data.index)
    for period in EMA_PERIODS:
        features[f"ema_{period}"] = ema(close, period)
    for period in SMA_PERIODS:
        features[f"sma_{period}"] = sma(close, period)
    features = pd.concat([features, macd(close)], axis=1)
    features["adx_14"] = adx(data, 14)
    return features
