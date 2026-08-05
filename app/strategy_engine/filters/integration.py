"""Integrate FilterPipeline with strategy TradePlans (backwards compatible)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.logging import get_logger
from app.strategy_engine.filters.catalog import create_filter
from app.strategy_engine.filters.pipeline import FilterPipeline
from app.strategy_engine.filters.profiles import StrategyFilterProfile
from app.strategy_engine.filters.schemas import PipelineResult, StrategyRecommendation
from app.strategy_engine.filters.strategy_profiles import get_strategy_filter_profile
from app.strategy_engine.models import SignalType, TradePlan

logger = get_logger(__name__)

# Feature-frame columns commonly copied into recommendation metadata
_FEATURE_META_KEYS = (
    "close",
    "high",
    "low",
    "open",
    "volume",
    "ema_9",
    "ema_20",
    "ema_21",
    "ema_50",
    "ema_200",
    "sma_20",
    "sma_50",
    "sma_200",
    "adx_14",
    "atr_14",
    "rsi_14",
    "obv",
    "vwap",
    "vwap_slope",
    "supertrend",
    "supertrend_direction",
    "relative_volume_20",
    "relative_volume_5",
    "volume_sma_20",
    "volume_sma_5",
    "gap_pct",
    "historical_volatility_20",
)


def enrich_metadata_from_features(
    features: pd.DataFrame | None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build filter metadata from the latest feature row."""
    meta: dict[str, Any] = dict(extra or {})
    if features is None or features.empty:
        return meta
    row = features.iloc[-1]
    for key in _FEATURE_META_KEYS:
        if key in features.columns:
            value = row[key]
            if value is None or (isinstance(value, float) and value != value):
                continue
            try:
                meta[key] = float(value)
            except (TypeError, ValueError):
                meta[key] = value
    # Convenience aliases used by filters
    if "ema_20" in meta and "ema_fast" not in meta:
        meta["ema_fast"] = meta["ema_20"]
    if "ema_50" in meta and "ema_slow" not in meta:
        meta["ema_slow"] = meta["ema_50"]
    if "close" in meta and "price" not in meta:
        meta["price"] = meta["close"]
    if "volume" in meta and "close" in meta and "dollar_volume" not in meta:
        meta["dollar_volume"] = float(meta["volume"]) * float(meta["close"])
    if "volume_sma_20" in meta and "close" in meta and "avg_dollar_volume" not in meta:
        meta["avg_dollar_volume"] = float(meta["volume_sma_20"]) * float(meta["close"])
    if "high" in meta and "low" in meta and "close" in meta and "range_pct" not in meta:
        close = float(meta["close"])
        if close > 0:
            meta["range_pct"] = (float(meta["high"]) - float(meta["low"])) / close * 100.0
    return meta


def build_pipeline_from_profile(
    profile: StrategyFilterProfile,
    *,
    enable_optional: set[str] | None = None,
    disable: set[str] | None = None,
    param_overrides: dict[str, dict[str, Any]] | None = None,
) -> FilterPipeline:
    """Assemble a FilterPipeline from a strategy profile."""
    specs = profile.resolve(
        enable_optional=enable_optional,
        disable=disable,
        param_overrides=param_overrides,
    )
    filters = [
        create_filter(
            spec.filter_id,
            enabled=True,
            priority=spec.priority,
            params=spec.params,
        )
        for spec in specs
    ]
    return FilterPipeline(filters=filters)


def recommendation_from_plan(
    plan: TradePlan,
    *,
    features: pd.DataFrame | None = None,
    metadata: dict[str, Any] | None = None,
) -> StrategyRecommendation:
    meta = enrich_metadata_from_features(features, extra=metadata)
    rec = StrategyRecommendation.from_trade_plan(plan)
    return rec.model_copy(update={"metadata": meta})


def trade_plan_from_filtered(
    original: TradePlan,
    result: PipelineResult,
    *,
    reject_as_hold: bool = True,
) -> TradePlan:
    """Map pipeline output back onto a TradePlan (preserves original on soft path)."""
    out = result.output
    if out.rejected and reject_as_hold:
        reasons = list(original.reasons) + [
            f"Filter rejected: {out.rejection_reason}",
            *out.filter_notes[-5:],
        ]
        return original.model_copy(
            update={
                "signal": SignalType.HOLD,
                "reasons": reasons,
                "confidence": min(float(original.confidence), 0.15),
            },
        )

    updates: dict[str, Any] = {
        "stop_loss": out.stop_loss,
        "take_profit_1": out.take_profit_1,
        "take_profit_2": out.take_profit_2,
        "risk_reward": out.risk_reward,
        "confidence": out.confidence,
        "reasons": list(dict.fromkeys([*original.reasons, *out.filter_notes])),
    }
    if out.rejected:
        updates["signal"] = SignalType.HOLD
    return original.model_copy(update=updates)


def apply_strategy_filter_pipeline(
    plan: TradePlan,
    *,
    profile: StrategyFilterProfile | None = None,
    features: pd.DataFrame | None = None,
    metadata: dict[str, Any] | None = None,
    enable_optional: set[str] | None = None,
    disable: set[str] | None = None,
    param_overrides: dict[str, dict[str, Any]] | None = None,
    reject_as_hold: bool = True,
) -> tuple[TradePlan, PipelineResult]:
    """Run the strategy's filter profile against a TradePlan.

    HOLD plans pass through without filter evaluation (raw logic preserved).
    """
    profile = profile or get_strategy_filter_profile(plan.strategy_name)
    if plan.signal is SignalType.HOLD:
        empty = FilterPipeline(filters=[])
        rec = recommendation_from_plan(plan, features=features, metadata=metadata)
        result = empty.run(rec)
        return plan, result

    pipeline = build_pipeline_from_profile(
        profile,
        enable_optional=enable_optional,
        disable=disable,
        param_overrides=param_overrides,
    )
    rec = recommendation_from_plan(plan, features=features, metadata=metadata)
    result = pipeline.run(rec)
    filtered_plan = trade_plan_from_filtered(plan, result, reject_as_hold=reject_as_hold)
    logger.info(
        "Filter pipeline for '%s': applied=%d skipped=%d rejected=%s signal=%s→%s",
        plan.strategy_name,
        result.filters_applied,
        result.filters_skipped,
        result.output.rejected,
        plan.signal.value,
        filtered_plan.signal.value,
    )
    return filtered_plan, result
