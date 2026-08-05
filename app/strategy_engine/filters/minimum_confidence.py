"""Minimum confidence filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class MinimumConfidenceFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence on 0–1 scale (StrategyRecommendation)",
    )
    accept_percent_scale: bool = Field(
        default=True,
        description="If confidence > 1, treat as 0–100 and normalize",
    )


class MinimumConfidenceFilter(FilterBase):
    """Require recommendation confidence to clear a minimum threshold."""

    def __init__(
        self,
        *,
        name: str = "minimum_confidence",
        enabled: bool = True,
        priority: int = 75,
        config: MinimumConfidenceFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MinimumConfidenceFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MinimumConfidenceFilterConfig:
        return self._config

    def normalized_confidence(self, recommendation: StrategyRecommendation) -> float:
        value = float(recommendation.confidence)
        if self._config.accept_percent_scale and value > 1.0:
            value = value / 100.0
        return value

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        conf = self.normalized_confidence(recommendation)
        if conf < self._config.min_confidence:
            raise FilterValidationError(
                f"{self.name}: confidence {conf:.4f} below min "
                f"{self._config.min_confidence:.4f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        conf = self.normalized_confidence(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass confidence={conf:.4f}",
            updates={"filter_confidence": float(conf)},
        )
