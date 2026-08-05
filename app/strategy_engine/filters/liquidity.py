"""Liquidity (dollar-volume) filter."""

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


class LiquidityFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dollar_volume_key: str = "dollar_volume"
    avg_dollar_volume_key: str = "avg_dollar_volume"
    volume_key: str = "volume"
    volume_sma_key: str = "volume_sma_20"
    min_dollar_volume: float = Field(default=0.0, ge=0.0)
    min_avg_dollar_volume: float = Field(
        default=10_000_000.0,
        ge=0.0,
        description="Minimum average daily rupee/dollar volume",
    )
    prefer_avg: bool = True


class LiquidityFilter(FilterBase):
    """Require sufficient traded value (liquidity)."""

    def __init__(
        self,
        *,
        name: str = "liquidity",
        enabled: bool = True,
        priority: int = 65,
        config: LiquidityFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or LiquidityFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> LiquidityFilterConfig:
        return self._config

    def _avg_dollar_volume(self, recommendation: StrategyRecommendation) -> float:
        avg = metadata_float(
            recommendation,
            self._config.avg_dollar_volume_key,
            required=False,
            filter_name=self.name,
        )
        if avg is not None:
            return avg
        vol_sma = metadata_float(
            recommendation,
            self._config.volume_sma_key,
            "volume_sma",
            required=False,
            filter_name=self.name,
        )
        price = resolve_price(recommendation, filter_name=self.name)
        if vol_sma is not None:
            return vol_sma * price
        raise FilterValidationError(
            f"{self.name}: missing avg dollar volume "
            f"({self._config.avg_dollar_volume_key} / {self._config.volume_sma_key})",
        )

    def _dollar_volume(self, recommendation: StrategyRecommendation) -> float | None:
        dv = metadata_float(
            recommendation,
            self._config.dollar_volume_key,
            required=False,
            filter_name=self.name,
        )
        if dv is not None:
            return dv
        volume = metadata_float(
            recommendation,
            self._config.volume_key,
            required=False,
            filter_name=self.name,
        )
        if volume is None:
            return None
        return volume * resolve_price(recommendation, filter_name=self.name)

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        if self._config.prefer_avg or self._config.min_avg_dollar_volume > 0:
            avg = self._avg_dollar_volume(recommendation)
            if avg < self._config.min_avg_dollar_volume:
                raise FilterValidationError(
                    f"{self.name}: avg dollar volume {avg:,.0f} below "
                    f"min {self._config.min_avg_dollar_volume:,.0f}",
                )
        if self._config.min_dollar_volume > 0:
            dv = self._dollar_volume(recommendation)
            if dv is None:
                raise FilterValidationError(f"{self.name}: missing dollar volume")
            if dv < self._config.min_dollar_volume:
                raise FilterValidationError(
                    f"{self.name}: dollar volume {dv:,.0f} below "
                    f"min {self._config.min_dollar_volume:,.0f}",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        avg = self._avg_dollar_volume(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass avg_dollar_volume={avg:,.0f}",
            updates={"filter_avg_dollar_volume": float(avg)},
        )
