"""Helpers for reading indicator / regime context from recommendation metadata."""

from __future__ import annotations

from typing import Any

from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


def metadata_value(
    recommendation: StrategyRecommendation,
    *keys: str,
    required: bool = True,
    filter_name: str = "filter",
) -> Any:
    """Return the first present metadata value for ``keys``."""
    meta = recommendation.metadata or {}
    for key in keys:
        if key in meta and meta[key] is not None:
            return meta[key]
    if required:
        joined = ", ".join(keys)
        raise FilterValidationError(
            f"{filter_name}: missing metadata key(s): {joined}",
        )
    return None


def metadata_float(
    recommendation: StrategyRecommendation,
    *keys: str,
    required: bool = True,
    filter_name: str = "filter",
) -> float | None:
    raw = metadata_value(
        recommendation,
        *keys,
        required=required,
        filter_name=filter_name,
    )
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise FilterValidationError(
            f"{filter_name}: metadata value is not numeric ({keys[0]}={raw!r})",
        ) from exc
    if value != value:  # NaN
        raise FilterValidationError(f"{filter_name}: metadata value is NaN ({keys[0]})")
    return value


def resolve_price(
    recommendation: StrategyRecommendation,
    *,
    price_keys: tuple[str, ...] = ("close", "price"),
    filter_name: str = "filter",
) -> float:
    """Prefer metadata close/price; fall back to entry_price."""
    priced = metadata_float(
        recommendation,
        *price_keys,
        required=False,
        filter_name=filter_name,
    )
    if priced is not None and priced > 0:
        return priced
    return float(recommendation.entry_price)


def annotate(
    recommendation: StrategyRecommendation,
    *,
    note: str,
    updates: dict[str, Any] | None = None,
) -> StrategyRecommendation:
    meta = dict(recommendation.metadata)
    if updates:
        meta.update(updates)
    return recommendation.model_copy(
        update={
            "filter_notes": [*recommendation.filter_notes, note],
            "metadata": meta,
        },
    )


def is_actionable(signal: SignalType) -> bool:
    return signal in {SignalType.BUY, SignalType.SELL, SignalType.EXIT}
