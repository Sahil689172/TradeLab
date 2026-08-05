"""Volatility regime filter."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class VolatilityRegime(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class VolatilityRegimeFilterConfig(BaseModel):
    """Classify volatility and allow only selected regimes.

    Uses ATR% of price when ``atr`` + price are present, otherwise
    ``historical_volatility`` (decimal or percent — auto-normalized).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    atr_key: str = "atr_14"
    hv_key: str = "historical_volatility_20"
    # ATR% thresholds (atr/price*100)
    low_atr_pct_max: float = Field(default=1.0, ge=0.0)
    high_atr_pct_min: float = Field(default=3.0, ge=0.0)
    # HV thresholds after normalizing to percent
    low_hv_pct_max: float = Field(default=15.0, ge=0.0)
    high_hv_pct_min: float = Field(default=35.0, ge=0.0)
    allowed_regimes: tuple[str, ...] = (
        VolatilityRegime.LOW.value,
        VolatilityRegime.NORMAL.value,
        VolatilityRegime.HIGH.value,
    )
    prefer_atr: bool = True


class VolatilityRegimeFilter(FilterBase):
    """Pass actionable signals only when volatility regime is allowed."""

    def __init__(
        self,
        *,
        name: str = "volatility_regime",
        enabled: bool = True,
        priority: int = 50,
        config: VolatilityRegimeFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or VolatilityRegimeFilterConfig()
        if threshold_overrides:
            self._config = base.model_copy(update=threshold_overrides)
        else:
            self._config = base

    @property
    def config(self) -> VolatilityRegimeFilterConfig:
        return self._config

    def classify(self, recommendation: StrategyRecommendation) -> VolatilityRegime:
        atr = metadata_float(
            recommendation,
            self._config.atr_key,
            "atr",
            required=False,
            filter_name=self.name,
        )
        price = metadata_float(
            recommendation,
            "close",
            "price",
            required=False,
            filter_name=self.name,
        )
        if price is None:
            price = float(recommendation.entry_price)

        if self._config.prefer_atr and atr is not None and price > 0:
            atr_pct = (atr / price) * 100.0
            if atr_pct <= self._config.low_atr_pct_max:
                return VolatilityRegime.LOW
            if atr_pct >= self._config.high_atr_pct_min:
                return VolatilityRegime.HIGH
            return VolatilityRegime.NORMAL

        hv = metadata_float(
            recommendation,
            self._config.hv_key,
            "historical_volatility",
            "hv",
            required=True,
            filter_name=self.name,
        )
        assert hv is not None
        hv_pct = hv * 100.0 if hv <= 1.5 else hv
        if hv_pct <= self._config.low_hv_pct_max:
            return VolatilityRegime.LOW
        if hv_pct >= self._config.high_hv_pct_min:
            return VolatilityRegime.HIGH
        return VolatilityRegime.NORMAL

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        regime = self.classify(recommendation)
        allowed = {item.strip().upper() for item in self._config.allowed_regimes}
        if regime.value not in allowed:
            raise FilterValidationError(
                f"{self.name}: volatility regime {regime.value} not allowed "
                f"(allowed={sorted(allowed)})",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        regime = self.classify(recommendation)
        return annotate(
            recommendation,
            note=f"{self.name}: pass regime={regime.value}",
            updates={"filter_volatility_regime": regime.value},
        )
