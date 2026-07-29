"""Volatility and range indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(data: pd.DataFrame) -> pd.Series:
    """Return one-period true range."""
    previous_close = data["close"].shift(1)
    return pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - previous_close).abs(),
            (data["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Wilder's Average True Range."""
    return true_range(data).ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()


def bollinger_bands(
    close: pd.Series,
    period: int = 20,
    standard_deviations: float = 2.0,
) -> pd.DataFrame:
    """Return Bollinger middle, upper, lower, and bandwidth."""
    middle = close.rolling(period, min_periods=period).mean()
    deviation = close.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + standard_deviations * deviation
    lower = middle - standard_deviations * deviation
    bandwidth = (upper - lower) / middle.replace(0, np.nan) * 100
    return pd.DataFrame(
        {
            "bollinger_middle_20": middle,
            "bollinger_upper_20": upper,
            "bollinger_lower_20": lower,
            "bollinger_bandwidth_20": bandwidth,
        },
        index=close.index,
    )


def historical_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """Return annualized rolling volatility of log returns."""
    log_return = np.log(close / close.shift(1))
    return log_return.rolling(period, min_periods=period).std(ddof=0) * np.sqrt(252)


def compute_volatility_features(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all volatility features."""
    close = data["close"].astype("float64")
    features = bollinger_bands(close)
    features.insert(0, "atr_14", atr(data, 14))
    features["historical_volatility_20"] = historical_volatility(close, 20)
    return features
