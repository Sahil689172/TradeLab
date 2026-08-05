"""Minimum absolute volume filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class MinimumVolumeFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    volume_key: str = "volume"
    min_volume: float = Field(default=100_000.0, ge=0.0)


class MinimumVolumeFilter(FilterBase):
    """Require an absolute minimum share volume on the bar."""

    def __init__(
        self,
        *,
        name: str = "minimum_volume",
        enabled: bool = True,
        priority: int = 66,
        config: MinimumVolumeFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MinimumVolumeFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MinimumVolumeFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        volume = metadata_float(
            recommendation,
            self._config.volume_key,
            filter_name=self.name,
        )
        assert volume is not None
        if volume < self._config.min_volume:
            raise FilterValidationError(
                f"{self.name}: volume {volume:,.0f} below min "
                f"{self._config.min_volume:,.0f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        volume = metadata_float(
            recommendation,
            self._config.volume_key,
            filter_name=self.name,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass volume={volume:,.0f}",
            updates={"filter_volume": float(volume)},
        )
