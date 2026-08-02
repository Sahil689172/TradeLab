"""Symbol resolution helpers for feature frames and strategies."""

from __future__ import annotations

import pandas as pd

from app.strategy_engine.exceptions import StrategyValidationError

# Sentinel used by strategy configs when no symbol has been provided yet.
UNBOUND_SYMBOL = "UNKNOWN"


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper()
    if not cleaned:
        raise StrategyValidationError("symbol must not be blank")
    return cleaned


def resolve_symbol_from_features(features: pd.DataFrame) -> str | None:
    """Extract a trading symbol from feature-frame metadata or a symbol column.

    Precedence:
        1. ``features.attrs["symbol"]``
        2. Latest non-null value of a ``symbol`` column
    """
    if not isinstance(features, pd.DataFrame):
        return None

    attr = features.attrs.get("symbol")
    if attr is not None and str(attr).strip():
        return normalize_symbol(str(attr))

    if "symbol" in features.columns:
        series = features["symbol"].dropna()
        if not series.empty:
            value = series.iloc[-1]
            if value is not None and str(value).strip():
                return normalize_symbol(str(value))
    return None


def attach_symbol(features: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Return a shallow copy of ``features`` with ``attrs["symbol"]`` set.

    Does not mutate the caller's frame. Downstream strategies/runners read the
    symbol from attrs so TradePlan / TradeRecommendation stay aligned.
    """
    frame = features.copy(deep=False)
    frame.attrs = dict(features.attrs)
    frame.attrs["symbol"] = normalize_symbol(symbol)
    return frame
