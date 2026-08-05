"""SMA200 trend filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, metadata_float, resolve_price
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class SMA200FilterConfig(BaseModel):
    """Configurable thresholds for the SMA200 filter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sma_key: str = "sma_200"
    require_buy_above: bool = True
    require_sell_below: bool = False
    min_distance_pct: float = Field(default=0.0, ge=0.0)


class SMA200Filter(FilterBase):
    """Pass BUY only when price is above SMA200 (configurable)."""

    def __init__(
        self,
        *,
        name: str = "sma200",
        enabled: bool = True,
        priority: int = 20,
        config: SMA200FilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or SMA200FilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> SMA200FilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if recommendation.signal is SignalType.HOLD:
            return
        sma = metadata_float(
            recommendation,
            self._config.sma_key,
            "sma200",
            filter_name=self.name,
        )
        assert sma is not None
        price = resolve_price(recommendation, filter_name=self.name)
        buffer = abs(sma) * (self._config.min_distance_pct / 100.0)

        if recommendation.signal is SignalType.BUY and self._config.require_buy_above:
            if price < sma + buffer:
                raise FilterValidationError(
                    f"{self.name}: BUY blocked — price {price:.4f} below "
                    f"SMA200 {sma:.4f} (buffer={buffer:.4f})",
                )
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT} and self._config.require_sell_below:
            if price > sma - buffer:
                raise FilterValidationError(
                    f"{self.name}: SELL blocked — price {price:.4f} above "
                    f"SMA200 {sma:.4f} (buffer={buffer:.4f})",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if recommendation.signal is SignalType.HOLD:
            return annotate(recommendation, note=f"{self.name}: skipped HOLD")
        sma = metadata_float(
            recommendation,
            self._config.sma_key,
            "sma200",
            filter_name=self.name,
        )
        price = resolve_price(recommendation, filter_name=self.name)
        return annotate(
            recommendation,
            note=f"{self.name}: pass price={price:.4f} sma200={sma:.4f}",
            updates={"filter_sma200": float(sma), "filter_sma200_price": price},
        )
