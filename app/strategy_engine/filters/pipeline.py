"""Chainable filter pipeline — strategies never see which filters run."""

from __future__ import annotations

from collections.abc import Sequence

from app.core.logging import get_logger
from app.strategy_engine.filters.exceptions import FilterPipelineError, FilterValidationError
from app.strategy_engine.filters.protocols import FilterRegistryPort, StrategyFilterPort
from app.strategy_engine.filters.registry import FilterRegistry
from app.strategy_engine.filters.schemas import (
    FilterStepResult,
    PipelineResult,
    StrategyRecommendation,
)

logger = get_logger(__name__)


class FilterPipeline:
    """Run a ``StrategyRecommendation`` through enabled filters in priority order.

    Dependency injection
    --------------------
    Prefer injecting a ``FilterRegistry`` (or any ``FilterRegistryPort``).
    Alternatively pass an explicit ``filters`` sequence. Strategies must not
    construct or know about this pipeline's filters.
    """

    def __init__(
        self,
        registry: FilterRegistryPort | None = None,
        *,
        filters: Sequence[StrategyFilterPort] | None = None,
        stop_on_rejection: bool = True,
    ) -> None:
        if registry is not None and filters is not None:
            raise FilterPipelineError(
                "Provide either registry or filters, not both",
            )
        if registry is None and filters is None:
            registry = FilterRegistry()
        self._registry = registry
        self._filters = list(filters) if filters is not None else None
        self._stop_on_rejection = bool(stop_on_rejection)

    @property
    def registry(self) -> FilterRegistryPort | None:
        return self._registry

    def run(self, recommendation: StrategyRecommendation) -> PipelineResult:
        """Validate + apply each enabled filter; return filtered recommendation."""
        if not isinstance(recommendation, StrategyRecommendation):
            raise TypeError(
                "FilterPipeline.run expects StrategyRecommendation, "
                f"got {type(recommendation).__name__}",
            )

        current = recommendation
        steps: list[FilterStepResult] = []
        applied = 0
        skipped = 0

        for filter_ in self._iter_filters():
            if not filter_.enabled:
                skipped += 1
                steps.append(
                    FilterStepResult(
                        filter_name=filter_.name,
                        priority=filter_.priority,
                        enabled=False,
                        applied=False,
                        skipped=True,
                        skip_reason="disabled",
                    ),
                )
                continue

            try:
                filter_.validate(current)
            except FilterValidationError as exc:
                logger.info(
                    "Filter '%s' validation failed: %s",
                    filter_.name,
                    exc,
                )
                rejected = current.model_copy(
                    update={
                        "rejected": True,
                        "rejection_reason": str(exc),
                        "filter_notes": [
                            *current.filter_notes,
                            f"{filter_.name}: {exc}",
                        ],
                    },
                )
                steps.append(
                    FilterStepResult(
                        filter_name=filter_.name,
                        priority=filter_.priority,
                        enabled=True,
                        applied=False,
                        skipped=True,
                        skip_reason=str(exc),
                        recommendation=rejected,
                    ),
                )
                skipped += 1
                if self._stop_on_rejection:
                    return PipelineResult(
                        input=recommendation,
                        output=rejected,
                        steps=steps,
                        filters_applied=applied,
                        filters_skipped=skipped,
                    )
                current = rejected
                continue

            current = filter_.apply(current)
            if not isinstance(current, StrategyRecommendation):
                raise FilterPipelineError(
                    f"Filter '{filter_.name}' apply() must return "
                    f"StrategyRecommendation, got {type(current).__name__}",
                )
            applied += 1
            steps.append(
                FilterStepResult(
                    filter_name=filter_.name,
                    priority=filter_.priority,
                    enabled=True,
                    applied=True,
                    skipped=False,
                    recommendation=current,
                ),
            )
            logger.debug("Filter '%s' applied", filter_.name)

            if current.rejected and self._stop_on_rejection:
                return PipelineResult(
                    input=recommendation,
                    output=current,
                    steps=steps,
                    filters_applied=applied,
                    filters_skipped=skipped,
                )

        return PipelineResult(
            input=recommendation,
            output=current,
            steps=steps,
            filters_applied=applied,
            filters_skipped=skipped,
        )

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        """Convenience: return only the filtered recommendation."""
        return self.run(recommendation).output

    def _iter_filters(self) -> list[StrategyFilterPort]:
        if self._filters is not None:
            return sorted(self._filters, key=lambda item: (item.priority, item.name))
        assert self._registry is not None
        return self._registry.list_enabled()
