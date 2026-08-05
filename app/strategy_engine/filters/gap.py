"""Opening gap filter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.strategy_engine.filters.base import FilterBase
from app.strategy_engine.filters.context import annotate, is_actionable, metadata_float
from app.strategy_engine.filters.exceptions import FilterValidationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class GapFilterConfig(BaseModel):
    """Gate trades by opening gap size.

    ``gap_pct`` is expected as percent (feature_engine price.gap_pct style),
    e.g. 2.5 means 2.5%. Set ``gap_as_fraction=True`` if values are 0.025.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gap_key: str = "gap_pct"
    max_abs_gap_pct: float | None = Field(
        default=5.0,
        ge=0.0,
        description="Reject when |gap| exceeds this percent (None = no max)",
    )
    min_abs_gap_pct: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional minimum |gap| for gap-and-go style setups",
    )
    gap_as_fraction: bool = False
    allow_missing_gap: bool = False


class GapFilter(FilterBase):
    """Reject (or require) gaps outside configurable bounds."""

    def __init__(
        self,
        *,
        name: str = "gap",
        enabled: bool = True,
        priority: int = 67,
        config: GapFilterConfig | None = None,
        **threshold_overrides: object,
    ) -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        base = config or GapFilterConfig()
        self._config = base.model_copy(update=threshold_overrides) if threshold_overrides else base

    @property
    def config(self) -> GapFilterConfig:
        return self._config

    def _gap_pct(self, recommendation: StrategyRecommendation) -> float | None:
        raw = metadata_float(
            recommendation,
            self._config.gap_key,
            "gap",
            required=not self._config.allow_missing_gap,
            filter_name=self.name,
        )
        if raw is None:
            return None
        return raw * 100.0 if self._config.gap_as_fraction else raw

    def validate(self, recommendation: StrategyRecommendation) -> None:
        if not is_actionable(recommendation.signal):
            return
        gap = self._gap_pct(recommendation)
        if gap is None:
            return
        abs_gap = abs(gap)
        if abs_gap < self._config.min_abs_gap_pct:
            raise FilterValidationError(
                f"{self.name}: |gap| {abs_gap:.3f}% below min "
                f"{self._config.min_abs_gap_pct:.3f}%",
            )
        if (
            self._config.max_abs_gap_pct is not None
            and abs_gap > self._config.max_abs_gap_pct
        ):
            raise FilterValidationError(
                f"{self.name}: |gap| {abs_gap:.3f}% above max "
                f"{self._config.max_abs_gap_pct:.3f}%",
            )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        if not is_actionable(recommendation.signal):
            return annotate(recommendation, note=f"{self.name}: skipped non-actionable")
        gap = self._gap_pct(recommendation)
        note = f"{self.name}: pass gap={gap:.3f}%" if gap is not None else f"{self.name}: pass (no gap)"
        return annotate(
            recommendation,
            note=note,
            updates={"filter_gap_pct": float(gap) if gap is not None else None},
        )
