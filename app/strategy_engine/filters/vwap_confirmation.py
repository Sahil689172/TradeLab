"""VWAP confirmation filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import (
    annotate,
    is_actionable,
    metadata_float,
    resolve_price,
)
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class VWAPConfirmationFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    vwap_key: str = "vwap"
    require_buy_above: bool = True
    require_sell_below: bool = True
    tolerance_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Allowed distance from VWAP as percent of VWAP",
    )


class VWAPConfirmationFilter(FilterBase):
    """Confirm BUY above VWAP and SELL below VWAP (configurable)."""

    def __init__(
        self,
        *,
        name: str = "vwap_confirmation",
        enabled: bool = True,
        priority: int = 63,
        config: VWAPConfirmationFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or VWAPConfirmationFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> VWAPConfirmationFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        vwap = metadata_float(
            recommendation,
            self._config.vwap_key,
            "vwap_daily",
            filter_name=self.name,
        )
        assert vwap is not None
        if vwap <= 0:
            raise FilterValidationError(f"{self.name}: VWAP must be > 0")
        price = resolve_price(recommendation, filter_name=self.name)
        tol = abs(vwap) * (self._config.tolerance_pct / 100.0)

        if recommendation.signal is SignalType.BUY and self._config.require_buy_above:
            if price < vwap - tol:
                raise FilterValidationError(
                    f"{self.name}: BUY blocked — price {price:.4f} below "
                    f"VWAP {vwap:.4f} (tol={tol:.4f})",
                )
        if (
            recommendation.signal in {SignalType.SELL, SignalType.EXIT}
            and self._config.require_sell_below
        ):
            if price > vwap + tol:
                raise FilterValidationError(
                    f"{self.name}: SELL blocked — price {price:.4f} above "
                    f"VWAP {vwap:.4f} (tol={tol:.4f})",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        vwap = metadata_float(
            recommendation,
            self._config.vwap_key,
            "vwap_daily",
            filter_name=self.name,
        )
        price = resolve_price(recommendation, filter_name=self.name)
        return annotate(
            recommendation,
            note=f"{self.name}: pass price={price:.4f} vwap={vwap:.4f}",
            updates={"filter_vwap": float(vwap), "filter_vwap_price": price},
        )
