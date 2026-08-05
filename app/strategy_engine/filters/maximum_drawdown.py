"""Maximum account / portfolio drawdown filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class MaximumDrawdownFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    drawdown_key: str = "portfolio_drawdown_pct"
    max_drawdown_pct: float = Field(
        default=10.0,
        ge=0.0,
        description="Maximum allowed drawdown percent (10 = 10%)",
    )
    drawdown_as_fraction: bool = False
    block_new_entries_only: bool = Field(
        default=True,
        description="When True, only BUY signals are blocked at max DD",
    )


class MaximumDrawdownFilter(FilterBase):
    """Block new risk when portfolio drawdown exceeds a cap."""

    def __init__(
        self,
        *,
        name: str = "maximum_drawdown",
        enabled: bool = True,
        priority: int = 74,
        config: MaximumDrawdownFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MaximumDrawdownFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MaximumDrawdownFilterConfig:
        return self._config

    def _drawdown_pct(self, recommendation: StrategyRecommendation) -> float:
        raw = metadata_float(
            recommendation,
            self._config.drawdown_key,
            "drawdown_pct",
            "max_drawdown_pct",
            filter_name=self.name,
        )
        assert raw is not None
        value = abs(raw)
        return value * 100.0 if self._config.drawdown_as_fraction else value

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        from app.strategy_engine.models import SignalType

        if self._config.block_new_entries_only and recommendation.signal is not SignalType.BUY:
            return
        dd = self._drawdown_pct(recommendation)
        if dd > self._config.max_drawdown_pct:
            raise FilterValidationError(
                f"{self.name}: drawdown {dd:.2f}% exceeds max "
                f"{self._config.max_drawdown_pct:.2f}%",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        dd = self._drawdown_pct(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass drawdown={dd:.2f}%",
            updates={"filter_drawdown_pct": float(dd)},
        )
