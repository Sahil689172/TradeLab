"""ADX strength filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class ADXFilterConfig(BaseModel):
    """Configurable ADX thresholds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adx_key: str = "adx_14"
    min_adx: float = Field(default=20.0, ge=0.0)
    max_adx: float | None = Field(default=None, ge=0.0)


class ADXFilter(FilterBase):
    """Require ADX within a configurable strength band for actionable signals."""

    def __init__(
        self,
        *,
        name: str = "adx",
        enabled: bool = True,
        priority: int = 30,
        config: ADXFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or ADXFilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> ADXFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        adx = metadata_float(
            recommendation,
            self._config.adx_key,
            "adx",
            filter_name=self.name,
        )
        assert adx is not None
        if adx < self._config.min_adx:
            raise FilterValidationError(
                f"{self.name}: ADX {adx:.2f} below min_adx {self._config.min_adx:.2f}",
            )
        if self._config.max_adx is not None and adx > self._config.max_adx:
            raise FilterValidationError(
                f"{self.name}: ADX {adx:.2f} above max_adx {self._config.max_adx:.2f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        adx = metadata_float(
            recommendation,
            self._config.adx_key,
            "adx",
            filter_name=self.name,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass adx={adx:.2f} min={self._config.min_adx:.2f}",
            updates={"filter_adx": float(adx)},
        )
