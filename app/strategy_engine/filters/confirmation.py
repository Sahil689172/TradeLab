"""Higher-timeframe confirmation request API for strategies.

Strategies never import concrete filters. They attach a confirmation request
and HTF snapshot fields onto ``StrategyRecommendation.metadata``; the filter
pipeline enforces whatever was requested (or all enabled filters).
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.schemas import StrategyRecommendation

CONFIRMATIONS_REQUESTED_KEY = "confirmations_requested"
HTF_SNAPSHOT_KEY = "htf_snapshot"

# Canonical confirmation ids strategies may request
HTF_TREND = "htf_trend"
DAILY = "daily"
WEEKLY = "weekly"
MTF_EMA = "mtf_ema"
MTF_RSI = "mtf_rsi"
MTF_SUPERTREND = "mtf_supertrend"

ALL_HTF_CONFIRMATIONS: tuple[str, ...] = (
    HTF_TREND,
    DAILY,
    WEEKLY,
    MTF_EMA,
    MTF_RSI,
    MTF_SUPERTREND,
)


class HTFConfirmationRequest(BaseModel):
    """Declarative confirmation request a strategy can attach to metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmations: tuple[str, ...] = Field(default_factory=tuple)
    # Optional inline HTF values (also accepted as flat metadata keys)
    htf_trend: str | None = None
    daily_trend: str | None = None
    weekly_trend: str | None = None
    htf_ema_fast: float | None = None
    htf_ema_slow: float | None = None
    daily_ema_fast: float | None = None
    daily_ema_slow: float | None = None
    weekly_ema_fast: float | None = None
    weekly_ema_slow: float | None = None
    htf_rsi: float | None = None
    daily_rsi: float | None = None
    weekly_rsi: float | None = None
    htf_supertrend: float | None = None
    htf_supertrend_direction: str | None = None
    daily_supertrend_direction: str | None = None
    weekly_supertrend_direction: str | None = None
    htf_close: float | None = None
    daily_close: float | None = None
    weekly_close: float | None = None


def request_confirmations(
    recommendation: StrategyRecommendation,
    *confirmation_ids: str,
    snapshot: dict[str, Any] | HTFConfirmationRequest | None = None,
) -> StrategyRecommendation:
    """Attach confirmation ids (+ optional HTF snapshot) for the pipeline.

    Example::

        rec = request_confirmations(
            rec,
            "daily",
            "mtf_ema",
            snapshot={"daily_trend": "BULLISH", "daily_ema_fast": 100, "daily_ema_slow": 95},
        )
    """
    meta = dict(recommendation.metadata)
    existing = list(meta.get(CONFIRMATIONS_REQUESTED_KEY) or [])
    for item in confirmation_ids:
        key = str(item).strip().lower()
        if key and key not in existing:
            existing.append(key)
    meta[CONFIRMATIONS_REQUESTED_KEY] = existing

    if snapshot is not None:
        if isinstance(snapshot, HTFConfirmationRequest):
            payload = snapshot.model_dump(exclude_none=True)
            confs = payload.pop("confirmations", ())
            for item in confs:
                key = str(item).strip().lower()
                if key and key not in existing:
                    existing.append(key)
            meta[CONFIRMATIONS_REQUESTED_KEY] = existing
            meta.update(payload)
            meta[HTF_SNAPSHOT_KEY] = payload
        else:
            meta.update({k: v for k, v in snapshot.items() if v is not None})
            meta[HTF_SNAPSHOT_KEY] = dict(snapshot)

    return recommendation.model_copy(update={"metadata": meta})


def requested_confirmations(recommendation: StrategyRecommendation) -> set[str]:
    raw = recommendation.metadata.get(CONFIRMATIONS_REQUESTED_KEY) or ()
    if isinstance(raw, str):
        return {raw.strip().lower()}
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def confirmation_is_active(
    recommendation: StrategyRecommendation,
    confirmation_id: str,
    *,
    only_when_requested: bool,
) -> bool:
    """Return whether this confirmation should be evaluated."""
    if not only_when_requested:
        return True
    requested = requested_confirmations(recommendation)
    if not requested:
        return False
    return confirmation_id.strip().lower() in requested


def normalize_trend(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value).strip().upper()
    return str(value).strip().upper()


def merge_requested(
    recommendation: StrategyRecommendation,
    confirmation_ids: Iterable[str],
) -> StrategyRecommendation:
    return request_confirmations(recommendation, *confirmation_ids)
