"""ATR trailing stop filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import (
    annotate,
    is_actionable,
    metadata_float,
    resolve_price,
)
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class ATRTrailingStopFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    atr_key: str = "atr_14"
    atr_multiplier: float = Field(default=2.0, gt=0.0)
    extreme_key: str = "position_extreme"
    # Fallback extremes
    high_key: str = "highest_high_since_entry"
    low_key: str = "lowest_low_since_entry"
    current_trail_key: str = "trailing_stop"
    enforce_trail: bool = True
    tighten_only: bool = Field(
        default=True,
        description="Never loosen an existing trailing stop",
    )


class ATRTrailingStopFilter(FilterBase):
    """Maintain an ATR trailing stop from the favorable extreme since entry."""

    def __init__(
        self,
        *,
        name: str = "atr_trailing_stop",
        enabled: bool = True,
        priority: int = 71,
        config: ATRTrailingStopFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or ATRTrailingStopFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> ATRTrailingStopFilterConfig:
        return self._config

    def trail_price(self, recommendation: StrategyRecommendation) -> float:
        atr = metadata_float(
            recommendation,
            self._config.atr_key,
            "atr",
            filter_name=self.name,
        )
        assert atr is not None
        if atr <= 0:
            raise FilterValidationError(f"{self.name}: ATR must be > 0")
        distance = atr * self._config.atr_multiplier

        if recommendation.signal is SignalType.BUY:
            extreme = metadata_float(
                recommendation,
                self._config.extreme_key,
                self._config.high_key,
                required=False,
                filter_name=self.name,
            )
            if extreme is None:
                extreme = resolve_price(recommendation, filter_name=self.name)
            return float(extreme) - distance

        extreme = metadata_float(
            recommendation,
            self._config.extreme_key,
            self._config.low_key,
            required=False,
            filter_name=self.name,
        )
        if extreme is None:
            extreme = resolve_price(recommendation, filter_name=self.name)
        return float(extreme) + distance

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        # Computing trail validates ATR / extremes are available.
        trail = self.trail_price(recommendation)
        price = resolve_price(recommendation, filter_name=self.name)
        if recommendation.signal is SignalType.BUY and trail >= price:
            raise FilterValidationError(
                f"{self.name}: trailing stop {trail:.6g} not below price {price:.6g}",
            )
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT} and trail <= price:
            raise FilterValidationError(
                f"{self.name}: trailing stop {trail:.6g} not above price {price:.6g}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        trail = self.trail_price(recommendation)
        prior = metadata_float(
            recommendation,
            self._config.current_trail_key,
            required=False,
            filter_name=self.name,
        )
        if prior is not None and self._config.tighten_only:
            if recommendation.signal is SignalType.BUY:
                trail = max(trail, prior)
            else:
                trail = min(trail, prior)

        updates = {"filter_atr_trailing_stop": float(trail), self._config.current_trail_key: float(trail)}
        note = f"{self.name}: pass trail={trail:.6g}"
        annotated = annotate(recommendation, note=note, updates=updates)
        if self._config.enforce_trail:
            return annotated.model_copy(update={"stop_loss": float(trail)})
        return annotated
