"""OBV confirmation filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class OBVConfirmationFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    obv_key: str = "obv"
    obv_prev_key: str = "obv_prev"
    obv_slope_key: str = "obv_slope"
    min_slope: float = Field(
        default=0.0,
        description="Minimum OBV delta/slope confirming BUY (SELL uses -min_slope)",
    )
    require_rising_for_buy: bool = True
    require_falling_for_sell: bool = True


class OBVConfirmationFilter(FilterBase):
    """Confirm BUY with rising OBV and SELL with falling OBV."""

    def __init__(
        self,
        *,
        name: str = "obv_confirmation",
        enabled: bool = True,
        priority: int = 62,
        config: OBVConfirmationFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or OBVConfirmationFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> OBVConfirmationFilterConfig:
        return self._config

    def _slope(self, recommendation: StrategyRecommendation) -> float:
        slope = metadata_float(
            recommendation,
            self._config.obv_slope_key,
            required=False,
            filter_name=self.name,
        )
        if slope is not None:
            return slope
        obv = metadata_float(
            recommendation,
            self._config.obv_key,
            filter_name=self.name,
        )
        prev = metadata_float(
            recommendation,
            self._config.obv_prev_key,
            filter_name=self.name,
        )
        assert obv is not None and prev is not None
        return obv - prev

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        slope = self._slope(recommendation)
        if (
            recommendation.signal is SignalType.BUY
            and self._config.require_rising_for_buy
            and slope < self._config.min_slope
        ):
            raise FilterValidationError(
                f"{self.name}: BUY needs rising OBV "
                f"(slope={slope:.4f} < min={self._config.min_slope:.4f})",
            )
        if (
            recommendation.signal in {SignalType.SELL, SignalType.EXIT}
            and self._config.require_falling_for_sell
            and slope > -self._config.min_slope
        ):
            raise FilterValidationError(
                f"{self.name}: SELL needs falling OBV "
                f"(slope={slope:.4f} > {-self._config.min_slope:.4f})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        slope = self._slope(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass obv_slope={slope:.4f}",
            updates={"filter_obv_slope": float(slope)},
        )
