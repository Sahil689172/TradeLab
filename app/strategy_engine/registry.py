"""Dynamic registration of strategy implementations."""

from __future__ import annotations

from collections.abc import Mapping

from app.core.logging import get_logger
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyNotFoundError, StrategyRegistrationError

logger = get_logger(__name__)


class StrategyRegistry:
    """In-memory registry mapping strategy names to strategy instances."""

    def __init__(self) -> None:
        self._strategies: dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        """Register a strategy instance under ``strategy.name``.

        Raises:
            StrategyRegistrationError: When the name is blank or already taken.
            TypeError: When ``strategy`` is not a ``BaseStrategy`` instance.
        """
        if not isinstance(strategy, BaseStrategy):
            raise TypeError(
                f"Expected BaseStrategy instance, got {type(strategy).__name__}",
            )

        name = strategy.name.strip()
        if not name:
            raise StrategyRegistrationError("Strategy name must not be blank")
        if name in self._strategies:
            raise StrategyRegistrationError(
                f"Strategy '{name}' is already registered",
            )

        self._strategies[name] = strategy
        logger.info("Registered strategy '%s'", name)

    def unregister(self, name: str) -> None:
        """Remove a registered strategy by name.

        Raises:
            StrategyNotFoundError: When no strategy is registered under ``name``.
            StrategyRegistrationError: When ``name`` is blank.
        """
        key = name.strip()
        if not key:
            raise StrategyRegistrationError("Strategy name must not be blank")
        if key not in self._strategies:
            raise StrategyNotFoundError(f"Strategy '{key}' is not registered")

        del self._strategies[key]
        logger.info("Unregistered strategy '%s'", key)

    def get(self, name: str) -> BaseStrategy:
        """Return the strategy registered under ``name``.

        Raises:
            StrategyNotFoundError: When no strategy is registered under ``name``.
            StrategyRegistrationError: When ``name`` is blank.
        """
        key = name.strip()
        if not key:
            raise StrategyRegistrationError("Strategy name must not be blank")
        try:
            return self._strategies[key]
        except KeyError as exc:
            raise StrategyNotFoundError(f"Strategy '{key}' is not registered") from exc

    def list(self) -> list[str]:
        """Return registered strategy names in insertion order."""
        return list(self._strategies.keys())

    def clear(self) -> None:
        """Remove all registered strategies."""
        self._strategies.clear()

    def as_mapping(self) -> Mapping[str, BaseStrategy]:
        """Return a read-only view of registered strategies."""
        return self._strategies
