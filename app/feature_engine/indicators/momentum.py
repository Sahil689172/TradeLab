"""Momentum and oscillator indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Return Wilder's Relative Strength Index."""
    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    average_loss = (-delta.clip(upper=0)).ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period,
    ).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    return result.mask((average_loss == 0) & (average_gain > 0), 100.0)


def roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Return percentage rate of change."""
    return close.pct_change(periods=period, fill_method=None) * 100


def momentum(close: pd.Series, period: int = 10) -> pd.Series:
    """Return absolute price momentum."""
    return close - close.shift(period)


def cci(data: pd.DataFrame, period: int = 20) -> pd.Series:
    """Return Commodity Channel Index."""
    typical_price = (data["high"] + data["low"] + data["close"]) / 3
    moving_average = typical_price.rolling(period, min_periods=period).mean()
    mean_deviation = typical_price.rolling(period, min_periods=period).apply(
        lambda values: np.mean(np.abs(values - values.mean())),
        raw=True,
    )
    return (typical_price - moving_average) / (0.015 * mean_deviation.replace(0, np.nan))


def williams_r(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Williams %R."""
    highest = data["high"].rolling(period, min_periods=period).max()
    lowest = data["low"].rolling(period, min_periods=period).min()
    return -100 * (highest - data["close"]) / (highest - lowest).replace(0, np.nan)


def stochastic(data: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Return stochastic %K and three-period %D."""
    lowest = data["low"].rolling(period, min_periods=period).min()
    highest = data["high"].rolling(period, min_periods=period).max()
    k_value = 100 * (data["close"] - lowest) / (highest - lowest).replace(0, np.nan)
    return pd.DataFrame(
        {
            "stochastic_k_14": k_value,
            "stochastic_d_3": k_value.rolling(3, min_periods=3).mean(),
        },
        index=data.index,
    )


def compute_momentum_features(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all momentum features."""
    close = data["close"].astype("float64")
    features = pd.DataFrame(
        {
            "rsi_14": rsi(close, 14),
            "roc_12": roc(close, 12),
            "momentum_10": momentum(close, 10),
            "cci_20": cci(data, 20),
            "williams_r_14": williams_r(data, 14),
        },
        index=data.index,
    )
    return pd.concat([features, stochastic(data, 14)], axis=1)
