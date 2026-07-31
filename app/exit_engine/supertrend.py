"""SuperTrend calculation for exit evaluation (OHLC + ATR based)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.exit_engine.exceptions import ExitValidationError


def compute_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    period: int = 10,
    multiplier: float = 3.0,
    atr: pd.Series | None = None,
) -> pd.DataFrame:
    """Return SuperTrend line and direction.

    Columns:
        supertrend: float
        direction: 1 for bullish (support below price), -1 for bearish
    """
    if period < 1:
        raise ExitValidationError("supertrend period must be >= 1")
    if multiplier <= 0:
        raise ExitValidationError("supertrend multiplier must be > 0")
    if not (len(high) == len(low) == len(close)):
        raise ExitValidationError("high/low/close must be aligned")
    if len(close) == 0:
        raise ExitValidationError("Cannot compute SuperTrend on empty series")

    if atr is None:
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_series = true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    else:
        atr_series = pd.to_numeric(atr, errors="coerce")

    hl2 = (high.astype("float64") + low.astype("float64")) / 2.0
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()
    for i in range(1, len(close)):
        if np.isnan(basic_upper.iloc[i]) or np.isnan(basic_lower.iloc[i]):
            continue
        prev_upper = final_upper.iloc[i - 1]
        prev_lower = final_lower.iloc[i - 1]
        prev_close = float(close.iloc[i - 1])

        if np.isnan(prev_upper) or basic_upper.iloc[i] < prev_upper or prev_close > prev_upper:
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = prev_upper

        if np.isnan(prev_lower) or basic_lower.iloc[i] > prev_lower or prev_close < prev_lower:
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = prev_lower

    direction = pd.Series(index=close.index, dtype="float64")
    supertrend = pd.Series(index=close.index, dtype="float64")
    direction.iloc[0] = 1.0
    supertrend.iloc[0] = final_lower.iloc[0]

    for i in range(1, len(close)):
        prev_dir = direction.iloc[i - 1]
        if np.isnan(prev_dir):
            prev_dir = 1.0
        if prev_dir <= 0:
            if float(close.iloc[i]) > float(final_upper.iloc[i]):
                direction.iloc[i] = 1.0
            else:
                direction.iloc[i] = -1.0
        else:
            if float(close.iloc[i]) < float(final_lower.iloc[i]):
                direction.iloc[i] = -1.0
            else:
                direction.iloc[i] = 1.0

        supertrend.iloc[i] = (
            final_lower.iloc[i] if direction.iloc[i] > 0 else final_upper.iloc[i]
        )

    return pd.DataFrame(
        {
            "supertrend": supertrend.astype("float64"),
            "direction": direction.astype("float64"),
        },
        index=close.index,
    )
