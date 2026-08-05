"""Volume vs volume-SMA filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class VolumeSMAFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    volume_key: str = "volume"
    volume_sma_key: str = "volume_sma_20"
    min_volume_vs_sma: float = Field(
        default=1.0,
        gt=0.0,
        description="Require volume >= multiplier * volume SMA",
    )


class VolumeSMAFilter(FilterBase):
    """Require current volume to clear a multiple of its SMA."""

    def __init__(
        self,
        *,
        name: str = "volume_sma",
        enabled: bool = True,
        priority: int = 61,
        config: VolumeSMAFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or VolumeSMAFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> VolumeSMAFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        volume = metadata_float(
            recommendation,
            self._config.volume_key,
            filter_name=self.name,
        )
        sma = metadata_float(
            recommendation,
            self._config.volume_sma_key,
            "volume_sma",
            filter_name=self.name,
        )
        assert volume is not None and sma is not None
        if sma <= 0:
            raise FilterValidationError(f"{self.name}: volume SMA must be > 0")
        ratio = volume / sma
        if ratio < self._config.min_volume_vs_sma:
            raise FilterValidationError(
                f"{self.name}: volume/SMA ratio {ratio:.3f} below "
                f"min {self._config.min_volume_vs_sma:.3f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        volume = metadata_float(recommendation, self._config.volume_key, filter_name=self.name)
        sma = metadata_float(
            recommendation,
            self._config.volume_sma_key,
            "volume_sma",
            filter_name=self.name,
        )
        assert volume is not None and sma is not None
        ratio = volume / sma
        return annotate(
            recommendation,
            note=f"{self.name}: pass volume={volume:.0f} sma={sma:.0f} ratio={ratio:.3f}",
            updates={"filter_volume_sma_ratio": float(ratio)},
        )
