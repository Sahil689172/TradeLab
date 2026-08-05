"""Minimum risk/reward filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class RiskRewardFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    min_risk_reward: float = Field(default=1.5, gt=0.0)
    use_target: str = Field(
        default="take_profit_1",
        description="take_profit_1 or take_profit_2",
    )
    recompute_from_prices: bool = Field(
        default=True,
        description="When True, RR is computed from entry/stop/target",
    )
    tolerance: float = Field(default=1e-9, ge=0.0)


class RiskRewardFilter(FilterBase):
    """Require recommendation risk/reward to clear a minimum threshold."""

    def __init__(
        self,
        *,
        name: str = "risk_reward",
        enabled: bool = True,
        priority: int = 73,
        config: RiskRewardFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or RiskRewardFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> RiskRewardFilterConfig:
        return self._config

    def realized_rr(self, recommendation: StrategyRecommendation) -> float:
        if not self._config.recompute_from_prices:
            return float(recommendation.risk_reward)

        entry = float(recommendation.entry_price)
        stop = float(recommendation.stop_loss)
        if self._config.use_target == "take_profit_2":
            target = float(recommendation.take_profit_2)
        else:
            target = float(recommendation.take_profit_1)

        if recommendation.signal is SignalType.BUY:
            risk = entry - stop
            reward = target - entry
        elif recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            risk = stop - entry
            reward = entry - target
        else:
            return float(recommendation.risk_reward)

        if risk <= self._config.tolerance:
            raise FilterValidationError(f"{self.name}: non-positive risk distance ({risk})")
        return reward / risk

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        rr = self.realized_rr(recommendation)
        if rr + self._config.tolerance < self._config.min_risk_reward:
            raise FilterValidationError(
                f"{self.name}: risk/reward {rr:.4f} below min "
                f"{self._config.min_risk_reward:.4f}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        rr = self.realized_rr(recommendation)
        annotated = annotate(
            recommendation,
            note=f"{self.name}: pass rr={rr:.4f}",
            updates={"filter_risk_reward": float(rr)},
        )
        return annotated.model_copy(update={"risk_reward": float(rr)})
