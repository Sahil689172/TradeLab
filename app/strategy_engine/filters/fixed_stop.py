"""Fixed percentage / points stop filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class FixedStopFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stop_pct: float | None = Field(
        default=0.02,
        gt=0.0,
        description="Fraction of entry (0.02 = 2%)",
    )
    stop_points: float | None = Field(
        default=None,
        gt=0.0,
        description="Absolute price distance; overrides stop_pct when set",
    )
    enforce_stop: bool = True
    tolerance: float = Field(default=1e-6, ge=0.0)

    @model_validator(mode="after")
    def require_one_mode(self) -> FixedStopFilterConfig:
        if self.stop_points is None and self.stop_pct is None:
            raise ValueError("Provide stop_pct or stop_points")
        return self


class FixedStopFilter(FilterBase):
    """Enforce a fixed percent or points stop from entry."""

    def __init__(
        self,
        *,
        name: str = "fixed_stop",
        enabled: bool = True,
        priority: int = 72,
        config: FixedStopFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or FixedStopFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> FixedStopFilterConfig:
        return self._config

    def fixed_stop_price(self, recommendation: StrategyRecommendation) -> float:
        entry = float(recommendation.entry_price)
        if self._config.stop_points is not None:
            distance = float(self._config.stop_points)
        else:
            assert self._config.stop_pct is not None
            distance = entry * float(self._config.stop_pct)
        if recommendation.signal is SignalType.BUY:
            return entry - distance
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return entry + distance
        return recommendation.stop_loss

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        expected = self.fixed_stop_price(recommendation)
        stop = float(recommendation.stop_loss)
        # Geometry check only — enforce happens in apply.
        entry = float(recommendation.entry_price)
        tol = self._config.tolerance
        if recommendation.signal is SignalType.BUY and stop >= entry - tol:
            raise FilterValidationError(
                f"{self.name}: BUY stop {stop:.6g} must be below entry {entry:.6g}",
            )
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT} and stop <= entry + tol:
            raise FilterValidationError(
                f"{self.name}: SELL stop {stop:.6g} must be above entry {entry:.6g}",
            )
        _ = expected  # computed for fail-fast on bad config / entry

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        stop = self.fixed_stop_price(recommendation)
        annotated = annotate(
            recommendation,
            note=f"{self.name}: pass fixed_stop={stop:.6g}",
            updates={"filter_fixed_stop": float(stop)},
        )
        if self._config.enforce_stop:
            return annotated.model_copy(update={"stop_loss": float(stop)})
        return annotated
