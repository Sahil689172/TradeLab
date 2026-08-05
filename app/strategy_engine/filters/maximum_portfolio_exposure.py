"""Maximum portfolio exposure filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class MaximumPortfolioExposureFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current_exposure_key: str = "current_exposure_pct"
    proposed_exposure_key: str = "proposed_exposure_pct"
    position_notional_key: str = "position_notional"
    equity_key: str = "equity"
    max_exposure_pct: float = Field(
        default=100.0,
        gt=0.0,
        description="Max total portfolio exposure percent",
    )
    max_single_position_pct: float | None = Field(
        default=25.0,
        gt=0.0,
        description="Optional cap on the new position alone",
    )
    exposure_as_fraction: bool = False


class MaximumPortfolioExposureFilter(FilterBase):
    """Cap aggregate (and optional single-name) portfolio exposure."""

    def __init__(
        self,
        *,
        name: str = "maximum_portfolio_exposure",
        enabled: bool = True,
        priority: int = 76,
        config: MaximumPortfolioExposureFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MaximumPortfolioExposureFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MaximumPortfolioExposureFilterConfig:
        return self._config

    def _as_pct(self, value: float) -> float:
        return value * 100.0 if self._config.exposure_as_fraction else value

    def proposed_pct(self, recommendation: StrategyRecommendation) -> float:
        proposed = metadata_float(
            recommendation,
            self._config.proposed_exposure_key,
            required=False,
            filter_name=self.name,
        )
        if proposed is not None:
            return self._as_pct(proposed)
        notional = metadata_float(
            recommendation,
            self._config.position_notional_key,
            "notional",
            required=False,
            filter_name=self.name,
        )
        equity = metadata_float(
            recommendation,
            self._config.equity_key,
            "account_equity",
            required=False,
            filter_name=self.name,
        )
        if notional is not None and equity is not None and equity > 0:
            return (notional / equity) * 100.0
        raise FilterValidationError(
            f"{self.name}: missing proposed exposure "
            f"({self._config.proposed_exposure_key} or notional/equity)",
        )

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        # Exits reduce exposure — do not block.
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return

        current = metadata_float(
            recommendation,
            self._config.current_exposure_key,
            "exposure_pct",
            required=False,
            filter_name=self.name,
        )
        current_pct = self._as_pct(current) if current is not None else 0.0
        proposed = self.proposed_pct(recommendation)

        if (
            self._config.max_single_position_pct is not None
            and proposed > self._config.max_single_position_pct
        ):
            raise FilterValidationError(
                f"{self.name}: proposed position {proposed:.2f}% exceeds "
                f"single-name max {self._config.max_single_position_pct:.2f}%",
            )

        total = current_pct + proposed
        if total > self._config.max_exposure_pct:
            raise FilterValidationError(
                f"{self.name}: total exposure {total:.2f}% exceeds max "
                f"{self._config.max_exposure_pct:.2f}% "
                f"(current={current_pct:.2f} proposed={proposed:.2f})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return annotate(recommendation, note=f"{self.name}: skipped exit")
        proposed = self.proposed_pct(recommendation)
        current = metadata_float(
            recommendation,
            self._config.current_exposure_key,
            "exposure_pct",
            required=False,
            filter_name=self.name,
        )
        current_pct = self._as_pct(current) if current is not None else 0.0
        return annotate(
            recommendation,
            note=(
                f"{self.name}: pass exposure "
                f"current={current_pct:.2f}% proposed={proposed:.2f}%"
            ),
            updates={
                "filter_proposed_exposure_pct": float(proposed),
                "filter_total_exposure_pct": float(current_pct + proposed),
            },
        )
