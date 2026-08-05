"""Multi-timeframe RSI confirmation filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.confirmation import MTF_RSI, confirmation_is_active
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class MultiTimeframeRSIFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rsi_keys: tuple[str, ...] = ("htf_rsi", "daily_rsi", "weekly_rsi", "rsi_14")
    # BUY: RSI should be above floor and below overbought
    buy_min_rsi: float = Field(default=45.0, ge=0.0, le=100.0)
    buy_max_rsi: float = Field(default=70.0, ge=0.0, le=100.0)
    # SELL: RSI should be below ceiling and above oversold
    sell_min_rsi: float = Field(default=30.0, ge=0.0, le=100.0)
    sell_max_rsi: float = Field(default=55.0, ge=0.0, le=100.0)
    only_when_requested: bool = False


class MultiTimeframeRSIFilter(FilterBase):
    """Confirm signals using higher-timeframe RSI bands."""

    confirmation_id = MTF_RSI

    def __init__(
        self,
        *,
        name: str = "mtf_rsi",
        enabled: bool = True,
        priority: int = 84,
        config: MultiTimeframeRSIFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MultiTimeframeRSIFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MultiTimeframeRSIFilterConfig:
        return self._config

    def _active(self, recommendation: StrategyRecommendation) -> bool:
        return confirmation_is_active(
            recommendation,
            self.confirmation_id,
            only_when_requested=self._config.only_when_requested,
        )

    def _rsi(self, recommendation: StrategyRecommendation) -> float:
        value = metadata_float(
            recommendation,
            *self._config.rsi_keys,
            filter_name=self.name,
        )
        assert value is not None
        return value

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal) or not self._active(recommendation):
            return
        rsi = self._rsi(recommendation)
        if recommendation.signal is SignalType.BUY:
            if rsi < self._config.buy_min_rsi or rsi > self._config.buy_max_rsi:
                raise FilterValidationError(
                    f"{self.name}: BUY RSI {rsi:.2f} outside "
                    f"[{self._config.buy_min_rsi:.2f}, {self._config.buy_max_rsi:.2f}]",
                )
        elif recommendation.signal in {SignalType.SELL, SignalType.EXIT}:
            if rsi < self._config.sell_min_rsi or rsi > self._config.sell_max_rsi:
                raise FilterValidationError(
                    f"{self.name}: SELL RSI {rsi:.2f} outside "
                    f"[{self._config.sell_min_rsi:.2f}, {self._config.sell_max_rsi:.2f}]",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if not self._active(recommendation):
            return annotate(recommendation, note=f"{self.name}: skipped (not requested)")
        rsi = self._rsi(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass htf_rsi={rsi:.2f}",
            updates={"filter_htf_rsi": float(rsi)},
        )
