"""Dynamic registration of strategy filters (DI-friendly)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from app.core.logging import get_logger
from app.strategy_engine.filters.exceptions import (
    FilterNotFoundError,
    FilterRegistrationError,
)
from app.strategy_engine.filters.protocols import StrategyFilterPort

logger = get_logger(__name__)


class FilterRegistry:
    """In-memory registry mapping filter names to filter instances.

    Inject this into ``FilterPipeline`` so pipelines never hard-code filters.
    """

    def __init__(self, filters: Sequence[StrategyFilterPort] | None = None) -> None:
        self._filters: dict[str, StrategyFilterPort] = {}
        if filters:
            for item in filters:
                self.register(item)

    def register(self, filter_: StrategyFilterPort) -> None:
        """Register a filter under ``filter_.name``.

        Raises:
            FilterRegistrationError: Blank or duplicate name.
            TypeError: Missing required filter attributes.
        """
        self._assert_filter_contract(filter_)
        name = filter_.name.strip()
        if not name:
            raise FilterRegistrationError("Filter name must not be blank")
        if name in self._filters:
            raise FilterRegistrationError(f"Filter '{name}' is already registered")

        self._filters[name] = filter_
        logger.info(
            "Registered strategy filter '%s' (enabled=%s priority=%s)",
            name,
            filter_.enabled,
            filter_.priority,
        )

    def unregister(self, name: str) -> None:
        key = name.strip()
        if not key:
            raise FilterRegistrationError("Filter name must not be blank")
        if key not in self._filters:
            raise FilterNotFoundError(f"Filter '{key}' is not registered")
        del self._filters[key]
        logger.info("Unregistered strategy filter '%s'", key)

    def get(self, name: str) -> StrategyFilterPort:
        key = name.strip()
        if not key:
            raise FilterRegistrationError("Filter name must not be blank")
        try:
            return self._filters[key]
        except KeyError as exc:
            raise FilterNotFoundError(f"Filter '{key}' is not registered") from exc

    def list_names(self) -> list[str]:
        """Registered filter names in insertion order."""
        return list(self._filters.keys())

    def list_all(self) -> list[StrategyFilterPort]:
        """All registered filters in insertion order."""
        return list(self._filters.values())

    def list_enabled(self) -> list[StrategyFilterPort]:
        """Enabled filters sorted by priority (ascending), then name."""
        enabled = [item for item in self._filters.values() if item.enabled]
        return sorted(enabled, key=lambda item: (item.priority, item.name))

    def clear(self) -> None:
        self._filters.clear()

    def extend(self, filters: Iterable[StrategyFilterPort]) -> None:
        for item in filters:
            self.register(item)

    def as_mapping(self) -> Mapping[str, StrategyFilterPort]:
        return self._filters

    @staticmethod
    def _assert_filter_contract(filter_: StrategyFilterPort) -> None:
        required = ("name", "enabled", "priority", "validate", "apply")
        missing = [attr for attr in required if not hasattr(filter_, attr)]
        if missing:
            raise TypeError(
                f"Filter is missing required attributes: {', '.join(missing)}",
            )
