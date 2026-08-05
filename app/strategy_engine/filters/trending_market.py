"""Trending market regime filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.market_structure.schemas import TrendDirection
from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_value
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class TrendingMarketFilterConfig(BaseModel):
    """Configurable trending-regime rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_keys: tuple[str, ...] = ("trend_direction", "market_structure", "regime")
    allowed_trends: tuple[str, ...] = (
        TrendDirection.BULLISH.value,
        TrendDirection.BEARISH.value,
    )
    require_bullish_for_buy: bool = Field(
        default=False,
        description="When True, BUY also requires BULLISH trend",
    )
    require_bearish_for_sell: bool = Field(
        default=False,
        description="When True, SELL/EXIT also requires BEARISH trend",
    )


class TrendingMarketFilter(FilterBase):
    """Allow actionable signals only in trending (non-sideways) regimes."""

    def __init__(
        self,
        *,
        name: str = "trending_market",
        enabled: bool = True,
        priority: int = 40,
        config: TrendingMarketFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or TrendingMarketFilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> TrendingMarketFilterConfig:
        return self._config

    def _trend(self, recommendation: StrategyRecommendation) -> str:
        raw = metadata_value(
            recommendation,
            *self._config.trend_keys,
            filter_name=self.name,
        )
        if hasattr(raw, "value"):
            return str(raw.value).strip().upper()
        return str(raw).strip().upper()

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        trend = self._trend(recommendation)
        allowed = {item.strip().upper() for item in self._config.allowed_trends}
        if trend not in allowed:
            raise FilterValidationError(
                f"{self.name}: trend {trend} not in allowed {sorted(allowed)}",
            )
        if (
            self._config.require_bullish_for_buy
            and recommendation.signal is SignalType.BUY
            and trend != TrendDirection.BULLISH.value
        ):
            raise FilterValidationError(
                f"{self.name}: BUY requires BULLISH trend (got {trend})",
            )
        if (
            self._config.require_bearish_for_sell
            and recommendation.signal in {SignalType.SELL, SignalType.EXIT}
            and trend != TrendDirection.BEARISH.value
        ):
            raise FilterValidationError(
                f"{self.name}: SELL requires BEARISH trend (got {trend})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        trend = self._trend(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass trend={trend}",
            updates={"filter_trend": trend},
        )
