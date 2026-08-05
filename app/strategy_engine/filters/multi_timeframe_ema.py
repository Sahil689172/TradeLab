"""Multi-timeframe EMA alignment filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.confirmation import MTF_EMA, confirmation_is_active
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation
from app.strategy_engine.models import SignalType


class MultiTimeframeEMAFilterConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # Prefer explicit HTF keys; fall back to daily then weekly pairs
    htf_fast_keys: tuple[str, ...] = ("htf_ema_fast", "daily_ema_fast", "weekly_ema_fast")
    htf_slow_keys: tuple[str, ...] = ("htf_ema_slow", "daily_ema_slow", "weekly_ema_slow")
    ltf_fast_keys: tuple[str, ...] = ("ema_fast", "ema_9", "ema_20")
    ltf_slow_keys: tuple[str, ...] = ("ema_slow", "ema_21", "ema_50")
    require_htf_stack: bool = True
    require_ltf_stack: bool = False
    only_when_requested: bool = False


class MultiTimeframeEMAFilter(FilterBase):
    """Require higher-timeframe (and optional LTF) EMA stack alignment."""

    confirmation_id = MTF_EMA

    def __init__(
        self,
        *,
        name: str = "mtf_ema",
        enabled: bool = True,
        priority: int = 83,
        config: MultiTimeframeEMAFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or MultiTimeframeEMAFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> MultiTimeframeEMAFilterConfig:
        return self._config

    def _active(self, recommendation: StrategyRecommendation) -> bool:
        return confirmation_is_active(
            recommendation,
            self.confirmation_id,
            only_when_requested=self._config.only_when_requested,
        )

    def _pair(
        self,
        recommendation: StrategyRecommendation,
        fast_keys: tuple[str, ...],
        slow_keys: tuple[str, ...],
    ) -> tuple[float, float]:
        fast = metadata_float(recommendation, *fast_keys, filter_name=self.name)
        slow = metadata_float(recommendation, *slow_keys, filter_name=self.name)
        assert fast is not None and slow is not None
        return fast, slow

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal) or not self._active(recommendation):
            return
        bullish = recommendation.signal is SignalType.BUY
        if self._config.require_htf_stack:
            fast, slow = self._pair(
                recommendation,
                self._config.htf_fast_keys,
                self._config.htf_slow_keys,
            )
            if bullish and fast < slow:
                raise FilterValidationError(
                    f"{self.name}: HTF EMA not bullish (fast={fast:.4f} < slow={slow:.4f})",
                )
            if not bullish and fast > slow:
                raise FilterValidationError(
                    f"{self.name}: HTF EMA not bearish (fast={fast:.4f} > slow={slow:.4f})",
                )
        if self._config.require_ltf_stack:
            fast, slow = self._pair(
                recommendation,
                self._config.ltf_fast_keys,
                self._config.ltf_slow_keys,
            )
            if bullish and fast < slow:
                raise FilterValidationError(
                    f"{self.name}: LTF EMA not bullish (fast={fast:.4f} < slow={slow:.4f})",
                )
            if not bullish and fast > slow:
                raise FilterValidationError(
                    f"{self.name}: LTF EMA not bearish (fast={fast:.4f} > slow={slow:.4f})",
                )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        if not self._active(recommendation):
            return annotate(recommendation, note=f"{self.name}: skipped (not requested)")
        fast, slow = self._pair(
            recommendation,
            self._config.htf_fast_keys,
            self._config.htf_slow_keys,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass htf_ema fast={fast:.4f} slow={slow:.4f}",
            updates={"filter_htf_ema_fast": float(fast), "filter_htf_ema_slow": float(slow)},
        )
