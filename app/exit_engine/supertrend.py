"""SuperTrend calculation for exit evaluation.

Canonical implementation lives in
``app.services.strategy_engine.indicators.supertrend``. This module re-exports
``compute_supertrend`` and maps validation errors to ``ExitValidationError``
so existing exit-engine callers keep working without duplicated math.
"""

from __future__ import annotations

import pandas as pd

from app.exit_engine.exceptions import ExitValidationError
from app.services.strategy_engine.indicators.supertrend import (
    SuperTrendValidationError,
)
from app.services.strategy_engine.indicators.supertrend import (
    compute_supertrend as _compute_supertrend,
)


def compute_supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    period: int = 10,
    multiplier: float = 3.0,
    atr: pd.Series | None = None,
) -> pd.DataFrame:
    """Return SuperTrend line and direction (thin wrapper over indicator service)."""
    try:
        return _compute_supertrend(
            high,
            low,
            close,
            period=period,
            multiplier=multiplier,
            atr=atr,
        )
    except SuperTrendValidationError as exc:
        raise ExitValidationError(str(exc)) from exc
