"""EMA200 trend filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, metadata_float, resolve_price
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class EMA200FilterConfig(BaseModel):
    """Configurable thresholds for the EMA200 filter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ema_key: str = "ema_200"
    require_buy_above: bool = True
    require_sell_below: bool = False
    min_distance_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional minimum |price-ema|/ema * 100 buffer",
    )


class EMA200Filter(FilterBase):
    """Pass BUY only when price is above EMA200 (configurable)."""

    def __init__(
        self,
        *,
        name: str = "ema200",
        enabled: bool = True,
        priority: int = 10,
        config: EMA200FilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or EMA200FilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> EMA200FilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if recommendation.signal is SignalType.HOLD:
            return
        ema = metadata_float(
            recommendation,
            self._config.ema_key,
            "ema200",
            filter_name=self.name,
        )
        assert ema is not None
        price = resolve_price(recommendation, filter_name=self.name)
        buffer = abs(ema) * (self._config.min_distance_pct / 100.0)

        if recommendation.signal is SignalType.BUY and self._config.require_buy_above:
            if price < ema + buffer:
                raise FilterValidationError(
                    f"{self.name}: BUY blocked — price {price:.4f} below "
                    f"EMA200 {ema:.4f} (buffer={buffer:.4f})",
                )
        if recommendation.signal in {SignalType.SELL, SignalType.EXIT} and self._config.require_sell_below:
            if price > ema - buffer:
                raise FilterValidationError(
                    f"{self.name}: SELL blocked — price {price:.4f} above "
                    f"EMA200 {ema:.4f} (buffer={buffer:.4f})",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if recommendation.signal is SignalType.HOLD:
            return annotate(recommendation, note=f"{self.name}: skipped HOLD")
        ema = metadata_float(
            recommendation,
            self._config.ema_key,
            "ema200",
            filter_name=self.name,
        )
        price = resolve_price(recommendation, filter_name=self.name)
        return annotate(
            recommendation,
            note=f"{self.name}: pass price={price:.4f} ema200={ema:.4f}",
            updates={"filter_ema200": float(ema), "filter_ema200_price": price},
        )
