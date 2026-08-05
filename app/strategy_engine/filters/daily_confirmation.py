"""Daily timeframe confirmation filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.confirmation import (
    DAILY,
    confirmation_is_active,
    normalize_trend,
)
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_value
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class DailyConfirmationFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_keys: tuple[str, ...] = ("daily_trend", "daily_trend_direction", "d1_trend")
    require_bullish_for_buy: bool = True
    require_bearish_for_sell: bool = True
    only_when_requested: bool = False


class DailyConfirmationFilter(FilterBase):
    """Confirm signals against the daily trend regime."""

    confirmation_id = DAILY

    def __init__(
        self,
        *,
        name: str = "daily_confirmation",
        enabled: bool = True,
        priority: int = 81,
        config: DailyConfirmationFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or DailyConfirmationFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> DailyConfirmationFilterConfig:
        return self._config

    def _active(self, recommendation: StrategyRecommendation) -> bool:
        return confirmation_is_active(
            recommendation,
            self.confirmation_id,
            only_when_requested=self._config.only_when_requested,
        )

    def _trend(self, recommendation: StrategyRecommendation) -> str:
        raw = metadata_value(
            recommendation,
            *self._config.trend_keys,
            filter_name=self.name,
        )
        return normalize_trend(raw)

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal) or not self._active(recommendation):
            return
        trend = self._trend(recommendation)
        if (
            self._config.require_bullish_for_buy
            and recommendation.signal is SignalType.BUY
            and trend != TrendDirection.BULLISH.value
        ):
            raise FilterValidationError(
                f"{self.name}: BUY requires daily BULLISH (got {trend})",
            )
        if (
            self._config.require_bearish_for_sell
            and recommendation.signal in {SignalType.SELL, SignalType.EXIT}
            and trend != TrendDirection.BEARISH.value
        ):
            raise FilterValidationError(
                f"{self.name}: SELL requires daily BEARISH (got {trend})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if not self._active(recommendation):
            return annotate(recommendation, note=f"{self.name}: skipped (not requested)")
        trend = self._trend(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass daily_trend={trend}",
            updates={"filter_daily_trend": trend},
        )
