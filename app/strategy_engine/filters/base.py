"""Abstract base class for strategy filters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.strategy_engine.filters.exceptions import FilterRegistrationError
from app.strategy_engine.filters.schemas import StrategyRecommendation


class FilterBase(ABC):
    """Reusable filter contract: ``name``, ``enabled``, ``priority``, validate/apply.

    Concrete filters (A4X.2+) subclass this. Strategies must not import filter
    implementations — only the pipeline consumes filters.

    ``BaseStrategyFilter`` is retained as a compatibility alias.
    """

    def __init__(
        self,
        *,
        name: str,
        enabled: bool = True,
        priority: int = 100,
    ) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise FilterRegistrationError("Filter name must not be blank")
        self._name = cleaned
        self._enabled = bool(enabled)
        self._priority = int(priority)

    @property
    def name(self) -> str:
        return self._name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    @property
    def priority(self) -> int:
        return self._priority

    @priority.setter
    def priority(self, value: int) -> None:
        self._priority = int(value)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    @abstractmethod
    def validate(self, recommendation: StrategyRecommendation) -> None:
        """Validate ``recommendation`` before ``apply``.

        Raises:
            FilterValidationError: When validation fails.
        """

    @abstractmethod
    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        """Transform or annotate ``recommendation`` and return the result."""


# A4X.1 compatibility alias
BaseStrategyFilter = FilterBase
