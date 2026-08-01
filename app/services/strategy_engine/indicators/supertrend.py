"""Reusable SuperTrend calculator for strategies, exits, and confluence.

Canonical SuperTrend math lives here. ``app.exit_engine.supertrend`` re-exports
``compute_supertrend`` so exit rules do not duplicate the algorithm.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class SuperTrendValidationError(ValueError):
    """Invalid inputs for SuperTrend computation."""


class SuperTrendSnapshot(BaseModel):
    """Latest-bar SuperTrend state for strategy / confluence consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    direction: float = Field(..., description="1 = bullish, -1 = bearish")
    previous_direction: float | None = None
    bullish: bool
    bearish: bool
    flipped_to_bullish: bool
    flipped_to_bearish: bool
    close_above: bool
    close_below: bool
    atr_period: int = Field(..., ge=1)
    multiplier: float = Field(..., gt=0.0)
    column: str = "supertrend"
    direction_column: str = "supertrend_direction"


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
        raise SuperTrendValidationError("supertrend period must be >= 1")
    if multiplier <= 0:
        raise SuperTrendValidationError("supertrend multiplier must be > 0")
    if not (len(high) == len(low) == len(close)):
        raise SuperTrendValidationError("high/low/close must be aligned")
    if len(close) == 0:
        raise SuperTrendValidationError("Cannot compute SuperTrend on empty series")

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


class SuperTrendService:
    """Injectable SuperTrend service for strategies and future confluence modules.

    Dependency-inject this service so SuperTrend Strategy, Exit Engine consumers,
    Confluence, and Strategy Builder share one calculation path.
    """

    def __init__(
        self,
        *,
        atr_period: int = 10,
        multiplier: float = 3.0,
        high_column: str = "high",
        low_column: str = "low",
        close_column: str = "close",
        atr_column: str | None = None,
        supertrend_column: str = "supertrend",
        direction_column: str = "supertrend_direction",
    ) -> None:
        if atr_period < 1:
            raise SuperTrendValidationError("atr_period must be >= 1")
        if multiplier <= 0:
            raise SuperTrendValidationError("multiplier must be > 0")
        self._atr_period = atr_period
        self._multiplier = multiplier
        self._high_column = high_column
        self._low_column = low_column
        self._close_column = close_column
        self._atr_column = atr_column
        self._supertrend_column = supertrend_column
        self._direction_column = direction_column

    @property
    def atr_period(self) -> int:
        return self._atr_period

    @property
    def multiplier(self) -> float:
        return self._multiplier

    @property
    def supertrend_column(self) -> str:
        return self._supertrend_column

    @property
    def direction_column(self) -> str:
        return self._direction_column

    def compute(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Return a two-column frame: supertrend, direction (index-aligned)."""
        self._validate(frame)
        atr = None
        if self._atr_column is not None and self._atr_column in frame.columns:
            atr = pd.to_numeric(frame[self._atr_column], errors="coerce")
        return compute_supertrend(
            pd.to_numeric(frame[self._high_column], errors="coerce"),
            pd.to_numeric(frame[self._low_column], errors="coerce"),
            pd.to_numeric(frame[self._close_column], errors="coerce"),
            period=self._atr_period,
            multiplier=self._multiplier,
            atr=atr,
        )

    def attach(self, frame: pd.DataFrame, *, overwrite: bool = False) -> pd.DataFrame:
        """Attach ``supertrend`` and ``supertrend_direction`` columns."""
        out = frame.copy()
        computed = self.compute(out)
        if not overwrite:
            if self._supertrend_column in out.columns or self._direction_column in out.columns:
                raise SuperTrendValidationError(
                    f"Columns {self._supertrend_column!r}/{self._direction_column!r} "
                    "already present; pass overwrite=True to replace",
                )
        out[self._supertrend_column] = computed["supertrend"].to_numpy()
        out[self._direction_column] = computed["direction"].to_numpy()
        return out

    def snapshot(self, frame: pd.DataFrame, *, close: float | None = None) -> SuperTrendSnapshot:
        """Latest-bar SuperTrend diagnostics (attaches if columns missing)."""
        if (
            self._supertrend_column not in frame.columns
            or self._direction_column not in frame.columns
        ):
            frame = self.attach(frame, overwrite=True)
        if len(frame) < 1:
            raise SuperTrendValidationError("Cannot snapshot empty frame")

        latest_close = (
            float(close)
            if close is not None
            else float(pd.to_numeric(frame[self._close_column], errors="coerce").iloc[-1])
        )
        value = float(frame[self._supertrend_column].iloc[-1])
        direction = float(frame[self._direction_column].iloc[-1])
        previous_direction: float | None = None
        if len(frame) >= 2:
            previous_direction = float(frame[self._direction_column].iloc[-2])

        bullish = direction > 0
        bearish = direction < 0
        flipped_to_bullish = (
            previous_direction is not None and previous_direction < 0 and bullish
        )
        flipped_to_bearish = (
            previous_direction is not None and previous_direction > 0 and bearish
        )
        return SuperTrendSnapshot(
            value=value,
            direction=direction,
            previous_direction=previous_direction,
            bullish=bullish,
            bearish=bearish,
            flipped_to_bullish=flipped_to_bullish,
            flipped_to_bearish=flipped_to_bearish,
            close_above=latest_close > value,
            close_below=latest_close < value,
            atr_period=self._atr_period,
            multiplier=self._multiplier,
            column=self._supertrend_column,
            direction_column=self._direction_column,
        )

    def _validate(self, frame: pd.DataFrame) -> None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise SuperTrendValidationError("frame must be a non-empty DataFrame")
        required = {self._high_column, self._low_column, self._close_column}
        missing = sorted(column for column in required if column not in frame.columns)
        if missing:
            raise SuperTrendValidationError(
                f"SuperTrend missing columns: {', '.join(missing)}",
            )
        if len(frame) < self._atr_period + 1:
            raise SuperTrendValidationError(
                f"Need at least {self._atr_period + 1} bars for SuperTrend",
            )
