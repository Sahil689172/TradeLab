"""Protocols for Dependency Injection into the strategy filter framework."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.strategy_engine.filters.schemas import StrategyRecommendation


@runtime_checkable
class StrategyFilterPort(Protocol):
    """Contract every strategy filter must satisfy.

    Strategies never depend on this protocol. Pipelines and registries do.
    """

    @property
    def name(self) -> str:
        """Stable filter identifier."""

    @property
    def enabled(self) -> bool:
        """When False, the pipeline skips this filter."""

    @property
    def priority(self) -> int:
        """Execution order key — lower values run first."""

    def validate(self, recommendation: StrategyRecommendation) -> None:
        """Validate ``recommendation`` for this filter.

        Raises:
            FilterValidationError: When the recommendation is unsuitable.
        """

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        """Return a (possibly transformed) recommendation."""


@runtime_checkable
class FilterRegistryPort(Protocol):
    """Lookup of registered filters for pipeline DI."""

    def get(self, name: str) -> StrategyFilterPort:
        ...

    def list_enabled(self) -> list[StrategyFilterPort]:
        ...

    def list_all(self) -> list[StrategyFilterPort]:
        ...


@runtime_checkable
class FilterPipelinePort(Protocol):
    """Run a recommendation through a chain of filters."""

    def run(self, recommendation: StrategyRecommendation) -> object:
        ...
