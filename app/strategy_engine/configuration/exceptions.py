"""Strategy configuration system exceptions."""

from __future__ import annotations


class StrategyConfigurationError(Exception):
    """Base error for the strategy configuration system."""


class StrategyConfigValidationError(StrategyConfigurationError, ValueError):
    """Raised when a strategy configuration fails validation."""


class StrategyConfigLoadError(StrategyConfigurationError):
    """Raised when a config file cannot be read or parsed."""


class StrategyConfigNotFoundError(StrategyConfigurationError, KeyError):
    """Raised when a strategy name has no registered configuration binding."""
