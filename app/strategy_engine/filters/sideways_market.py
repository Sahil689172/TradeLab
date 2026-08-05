"""Sideways market regime filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.market_structure.schemas import TrendDirection
from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_value
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class SidewaysMarketFilterConfig(BaseModel):
    """Configurable sideways-regime rules."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend_keys: tuple[str, ...] = ("trend_direction", "market_structure", "regime")
    sideways_labels: tuple[str, ...] = (TrendDirection.SIDEWAYS.value, "RANGE", "RANGING")


class SidewaysMarketFilter(FilterBase):
    """Allow actionable signals only in sideways / ranging regimes."""

    def __init__(
        self,
        *,
        name: str = "sideways_market",
        enabled: bool = True,
        priority: int = 40,
        config: SidewaysMarketFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or SidewaysMarketFilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> SidewaysMarketFilterConfig:
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
        allowed = {item.strip().upper() for item in self._config.sideways_labels}
        if trend not in allowed:
            raise FilterValidationError(
                f"{self.name}: trend {trend} is not sideways "
                f"(allowed={sorted(allowed)})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        trend = self._trend(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass sideways trend={trend}",
            updates={"filter_sideways": trend},
        )
