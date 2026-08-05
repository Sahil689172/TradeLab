"""Minimum position size filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class MinimumPositionSizeFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    quantity_key: str = "position_size"
    notional_key: str = "position_notional"
    min_quantity: float = Field(default=1.0, ge=0.0)
    min_notional: float = Field(default=0.0, ge=0.0)
    require_quantity: bool = True
    require_notional: bool = False


class MinimumPositionSizeFilter(FilterBase):
    """Reject undersized positions (shares and/or notional)."""

    def __init__(
        self,
        *,
        name: str = "minimum_position_size",
        enabled: bool = True,
        priority: int = 77,
        config: MinimumPositionSizeFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MinimumPositionSizeFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MinimumPositionSizeFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return

        if self._config.require_quantity or self._config.min_quantity > 0:
            qty = metadata_float(
                recommendation,
                self._config.quantity_key,
                "quantity",
                "qty",
                filter_name=self.name,
            )
            assert qty is not None
            if qty < self._config.min_quantity:
                raise FilterValidationError(
                    f"{self.name}: position size {qty:g} below min "
                    f"{self._config.min_quantity:g}",
                )

        if self._config.require_notional or self._config.min_notional > 0:
            notional = metadata_float(
                recommendation,
                self._config.notional_key,
                "notional",
                filter_name=self.name,
            )
            assert notional is not None
            if notional < self._config.min_notional:
                raise FilterValidationError(
                    f"{self.name}: notional {notional:,.2f} below min "
                    f"{self._config.min_notional:,.2f}",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            return annotate(recommendation, note=f"{self.name}: skipped exit")
        qty = metadata_float(
            recommendation,
            self._config.quantity_key,
            "quantity",
            "qty",
            required=False,
            filter_name=self.name,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass position_size={qty}",
            updates={"filter_position_size": float(qty) if qty is not None else None},
        )
