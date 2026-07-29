"""Volume and money-flow indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd


def obv(data: pd.DataFrame) -> pd.Series:
    """Return On-Balance Volume, starting at zero."""
    direction = np.sign(data["close"].diff()).fillna(0)
    return (direction * data["volume"]).cumsum().astype("float64")


def money_flow_index(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Money Flow Index."""
    typical_price = (data["high"] + data["low"] + data["close"]) / 3
    raw_flow = typical_price * data["volume"]
    direction = typical_price.diff()
    positive = raw_flow.where(direction > 0, 0.0)
    negative = raw_flow.where(direction < 0, 0.0)
    positive_sum = positive.rolling(period, min_periods=period).sum()
    negative_sum = negative.rolling(period, min_periods=period).sum()
    ratio = positive_sum / negative_sum.replace(0, np.nan)
    result = 100 - (100 / (1 + ratio))
    return result.mask((negative_sum == 0) & (positive_sum > 0), 100.0)


def compute_volume_features(data: pd.DataFrame) -> pd.DataFrame:
    """Compute all volume-derived features."""
    volume = data["volume"].astype("float64")
    volume_sma = volume.rolling(20, min_periods=20).mean()
    return pd.DataFrame(
        {
            "obv": obv(data),
            "money_flow_index_14": money_flow_index(data, 14),
            "volume_sma_20": volume_sma,
            "relative_volume_20": volume / volume_sma.replace(0, np.nan),
        },
        index=data.index,
    )
