"""Strategy filter framework exceptions."""

from __future__ import annotations


class StrategyFilterError(Exception):
    """Base error for the strategy filter framework."""


class FilterValidationError(StrategyFilterError, ValueError):
    """Raised when a filter rejects an incoming recommendation."""


class FilterRegistrationError(StrategyFilterError, ValueError):
    """Raised when filter registration or configuration is invalid."""


class FilterNotFoundError(StrategyFilterError):
    """Raised when a requested filter is not registered."""


class FilterPipelineError(StrategyFilterError):
    """Raised when the pipeline cannot execute (misconfiguration / empty chain)."""
