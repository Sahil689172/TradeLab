"""Relative volume filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class RelativeVolumeFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rvol_key: str = "relative_volume_20"
    min_relative_volume: float = Field(default=1.5, gt=0.0)
    max_relative_volume: float | None = Field(default=None, gt=0.0)


class RelativeVolumeFilter(FilterBase):
    """Require relative volume above a configurable floor."""

    def __init__(
        self,
        *,
        name: str = "relative_volume",
        enabled: bool = True,
        priority: int = 60,
        config: RelativeVolumeFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or RelativeVolumeFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> RelativeVolumeFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        rvol = metadata_float(
            recommendation,
            self._config.rvol_key,
            "relative_volume",
            "rvol",
            filter_name=self.name,
        )
        assert rvol is not None
        if rvol < self._config.min_relative_volume:
            raise FilterValidationError(
                f"{self.name}: relative volume {rvol:.3f} below "
                f"min {self._config.min_relative_volume:.3f}",
            )
        if (
            self._config.max_relative_volume is not None
            and rvol > self._config.max_relative_volume
        ):
            raise FilterValidationError(
                f"{self.name}: relative volume {rvol:.3f} above "
                f"max {self._config.max_relative_volume:.3f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        rvol = metadata_float(
            recommendation,
            self._config.rvol_key,
            "relative_volume",
            "rvol",
            filter_name=self.name,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass rvol={rvol:.3f}",
            updates={"filter_relative_volume": float(rvol)},
        )
