"""ATR-based initial stop filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class ATRStopFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    atr_key: str = "atr_14"
    atr_multiplier: float = Field(default=1.5, gt=0.0)
    enforce_stop: bool = Field(
        default=True,
        description="When True, apply() rewrites stop_loss to the ATR stop",
    )
    require_stop_at_least_atr: bool = Field(
        default=True,
        description="Reject when existing stop is tighter than ATR distance",
    )
    tolerance: float = Field(default=1e-6, ge=0.0)


class ATRStopFilter(FilterBase):
    """Compute / enforce an ATR multiple stop for actionable signals."""

    def __init__(
        self,
        *,
        name: str = "atr_stop",
        enabled: bool = True,
        priority: int = 70,
        config: ATRStopFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or ATRStopFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> ATRStopFilterConfig:
        return self._config

    def atr_stop_price(self, recommendation: StrategyRecommendation) -> float:
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
        entry = float(recommendation.entry_price)
        if recommendation.signal is SignalType.BUY:
            return entry - distance
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return entry + distance
        return recommendation.stop_loss

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        atr_stop = self.atr_stop_price(recommendation)
        entry = float(recommendation.entry_price)
        stop = float(recommendation.stop_loss)
        tol = self._config.tolerance

        if recommendation.signal is SignalType.BUY:
            if stop >= entry - tol:
                raise FilterValidationError(
                    f"{self.name}: BUY stop {stop:.6g} must be below entry {entry:.6g}",
                )
            if self._config.require_stop_at_least_atr and stop > atr_stop + tol:
                raise FilterValidationError(
                    f"{self.name}: BUY stop {stop:.6g} tighter than ATR stop {atr_stop:.6g}",
                )
        elif recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            if stop <= entry + tol:
                raise FilterValidationError(
                    f"{self.name}: SELL stop {stop:.6g} must be above entry {entry:.6g}",
                )
            if self._config.require_stop_at_least_atr and stop < atr_stop - tol:
                raise FilterValidationError(
                    f"{self.name}: SELL stop {stop:.6g} tighter than ATR stop {atr_stop:.6g}",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        atr_stop = self.atr_stop_price(recommendation)
        updates = {"filter_atr_stop": float(atr_stop)}
        note = f"{self.name}: pass atr_stop={atr_stop:.6g}"
        if self._config.enforce_stop:
            annotated = annotate(recommendation, note=note + " (enforced)", updates=updates)
            return annotated.model_copy(update={"stop_loss": float(atr_stop)})
        return annotate(recommendation, note=note, updates=updates)
