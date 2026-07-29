"""Price-action and candlestick features."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_price_features(data: pd.DataFrame) -> pd.DataFrame:
    """Compute return, gap, range, body, and wick percentages."""
    open_price = data["open"].astype("float64")
    high = data["high"].astype("float64")
    low = data["low"].astype("float64")
    close = data["close"].astype("float64")
    previous_close = close.shift(1)
    candle_range = (high - low).replace(0, np.nan)
    upper_body = pd.concat([open_price, close], axis=1).max(axis=1)
    lower_body = pd.concat([open_price, close], axis=1).min(axis=1)

    return pd.DataFrame(
        {
            "daily_return": close.pct_change(fill_method=None),
            "log_return": np.log(close / previous_close),
            "gap_pct": (open_price - previous_close) / previous_close * 100,
            "high_low_pct": (high - low) / low.replace(0, np.nan) * 100,
            "open_close_pct": (close - open_price) / open_price.replace(0, np.nan) * 100,
            "body_pct": (close - open_price).abs() / candle_range * 100,
            "upper_wick_pct": (high - upper_body) / candle_range * 100,
            "lower_wick_pct": (lower_body - low) / candle_range * 100,
        },
        index=data.index,
    )
