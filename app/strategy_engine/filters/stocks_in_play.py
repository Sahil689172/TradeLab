"""Stocks-in-play filter (elevated activity + range)."""

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


class StocksInPlayFilterConfig(BaseModel):
    """Classic 'stock in play' gates: relative volume + range/gap + min price."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rvol_key: str = "relative_volume_20"
    range_pct_key: str = "range_pct"
    gap_pct_key: str = "gap_pct"
    min_relative_volume: float = Field(default=2.0, gt=0.0)
    min_range_pct: float = Field(
        default=2.0,
        ge=0.0,
        description="Intraday high-low range as percent of price",
    )
    min_abs_gap_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional minimum |gap| percent (0 = not required)",
    )
    min_price: float = Field(default=0.0, ge=0.0)
    require_range_or_gap: bool = Field(
        default=True,
        description="Pass if range OR |gap| clears its minimum (when gap min > 0)",
    )


class StocksInPlayFilter(FilterBase):
    """Flag names that are 'in play': strong relative volume and movement."""

    def __init__(
        self,
        *,
        name: str = "stocks_in_play",
        enabled: bool = True,
        priority: int = 64,
        config: StocksInPlayFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or StocksInPlayFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> StocksInPlayFilterConfig:
        return self._config

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        price = resolve_price(recommendation, filter_name=self.name)
        if price < self._config.min_price:
            raise FilterValidationError(
                f"{self.name}: price {price:.4f} below min_price {self._config.min_price:.4f}",
            )

        rvol = metadata_float(
            recommendation,
            self._config.rvol_key,
            "relative_volume",
            "rvol",
            filter_name=self.name,
        )
        assert rvol is not None
        if rvol < self._config.min_relative_volume:
            raise FilterValidationError(
                f"{self.name}: rvol {rvol:.3f} below min "
                f"{self._config.min_relative_volume:.3f}",
            )

        range_pct = metadata_float(
            recommendation,
            self._config.range_pct_key,
            "day_range_pct",
            required=False,
            filter_name=self.name,
        )
        gap_pct = metadata_float(
            recommendation,
            self._config.gap_pct_key,
            required=False,
            filter_name=self.name,
        )
        # Derive range from high/low if needed
        if range_pct is None:
            high = metadata_float(recommendation, "high", required=False, filter_name=self.name)
            low = metadata_float(recommendation, "low", required=False, filter_name=self.name)
            if high is not None and low is not None and price > 0:
                range_pct = ((high - low) / price) * 100.0

        range_ok = range_pct is not None and range_pct >= self._config.min_range_pct
        gap_ok = (
            self._config.min_abs_gap_pct > 0
            and gap_pct is not None
            and abs(gap_pct) >= self._config.min_abs_gap_pct
        )

        if self._config.require_range_or_gap:
            if self._config.min_abs_gap_pct > 0:
                if not (range_ok or gap_ok):
                    raise FilterValidationError(
                        f"{self.name}: need range>={self._config.min_range_pct:g}% "
                        f"or |gap|>={self._config.min_abs_gap_pct:g}% "
                        f"(range={range_pct}, gap={gap_pct})",
                    )
            elif not range_ok:
                raise FilterValidationError(
                    f"{self.name}: range_pct {range_pct} below "
                    f"min {self._config.min_range_pct:g}",
                )
        elif not range_ok:
            raise FilterValidationError(
                f"{self.name}: range_pct {range_pct} below min {self._config.min_range_pct:g}",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        rvol = metadata_float(
            recommendation,
            self._config.rvol_key,
            "relative_volume",
            "rvol",
            filter_name=self.name,
        )
        return annotate(
            recommendation,
            note=f"{self.name}: pass in-play rvol={rvol:.3f}",
            updates={"filter_stocks_in_play": True, "filter_sip_rvol": float(rvol)},
        )
