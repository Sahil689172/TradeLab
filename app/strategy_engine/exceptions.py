"""Exceptions raised by the strategy engine foundation."""

from __future__ import annotations


class StrategyEngineError(Exception):
    """Base error for strategy engine failures."""


class StrategyValidationError(StrategyEngineError):
    """Raised when strategy input validation fails."""


class StrategyNotFoundError(StrategyEngineError):
    """Raised when a requested strategy is not registered."""


class StrategyRegistrationError(StrategyEngineError):
    """Raised when strategy registration or unregistration is invalid."""
