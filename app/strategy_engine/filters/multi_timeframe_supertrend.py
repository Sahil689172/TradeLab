"""Multi-timeframe SuperTrend confirmation filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.confirmation import (
    MTF_SUPERTREND,
    confirmation_is_active,
    normalize_trend,
)
from app.strategy_engine.filters.context import (
    annotate,
    is_actionable,
    metadata_float,
    metadata_value,
    resolve_price,
)
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType

_BULLISH = {"BULLISH", "UP", "LONG", "1", "+1"}
_BEARISH = {"BEARISH", "DOWN", "SHORT", "-1"}


class MultiTimeframeSuperTrendFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direction_keys: tuple[str, ...] = (
        "htf_supertrend_direction",
        "daily_supertrend_direction",
        "weekly_supertrend_direction",
        "supertrend_direction",
    )
    level_keys: tuple[str, ...] = (
        "htf_supertrend",
        "daily_supertrend",
        "weekly_supertrend",
        "supertrend",
    )
    close_keys: tuple[str, ...] = ("htf_close", "daily_close", "weekly_close", "close")
    require_direction_align: bool = True
    require_price_side: bool = Field(
        default=True,
        description="BUY: close above ST level; SELL: close below",
    )
    only_when_requested: bool = False


class MultiTimeframeSuperTrendFilter(FilterBase):
    """Confirm signals using higher-timeframe SuperTrend direction / side."""

    confirmation_id = MTF_SUPERTREND

    def __init__(
        self,
        *,
        name: str = "mtf_supertrend",
        enabled: bool = True,
        priority: int = 85,
        config: MultiTimeframeSuperTrendFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MultiTimeframeSuperTrendFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MultiTimeframeSuperTrendFilterConfig:
        return self._config

    def _active(self, recommendation: StrategyRecommendation) -> bool:
        return confirmation_is_active(
            recommendation,
            self.confirmation_id,
            only_when_requested=self._config.only_when_requested,
        )

    def _direction(self, recommendation: StrategyRecommendation) -> str | None:
        raw = metadata_value(
            recommendation,
            *self._config.direction_keys,
            required=False,
            filter_name=self.name,
        )
        if raw is None:
            return None
        return normalize_trend(raw)

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal) or not self._active(recommendation):
            return
        direction = self._direction(recommendation)
        bullish_signal = recommendation.signal is SignalType.BUY

        if self._config.require_direction_align:
            if direction is None:
                raise FilterValidationError(
                    f"{self.name}: missing SuperTrend direction metadata",
                )
            if bullish_signal and direction not in _BULLISH:
                raise FilterValidationError(
                    f"{self.name}: BUY requires bullish HTF SuperTrend (got {direction})",
                )
            if not bullish_signal and direction not in _BEARISH:
                raise FilterValidationError(
                    f"{self.name}: SELL requires bearish HTF SuperTrend (got {direction})",
                )

        if self._config.require_price_side:
            level = metadata_float(
                recommendation,
                *self._config.level_keys,
                required=False,
                filter_name=self.name,
            )
            if level is None:
                raise FilterValidationError(
                    f"{self.name}: missing SuperTrend level metadata",
                )
            close = metadata_float(
                recommendation,
                *self._config.close_keys,
                required=False,
                filter_name=self.name,
            )
            if close is None:
                close = resolve_price(recommendation, filter_name=self.name)
            if bullish_signal and close < level:
                raise FilterValidationError(
                    f"{self.name}: BUY blocked — close {close:.4f} below ST {level:.4f}",
                )
            if not bullish_signal and close > level:
                raise FilterValidationError(
                    f"{self.name}: SELL blocked — close {close:.4f} above ST {level:.4f}",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if not self._active(recommendation):
            return annotate(recommendation, note=f"{self.name}: skipped (not requested)")
        direction = self._direction(recommendation) or "N/A"
        return annotate(
            recommendation,
            note=f"{self.name}: pass supertrend_direction={direction}",
            updates={"filter_htf_supertrend_direction": direction},
        )
