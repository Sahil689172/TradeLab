"""Exceptions raised by the indicator adapter."""

from __future__ import annotations


class IndicatorAdapterError(Exception):
    """Base error for indicator adapter failures."""


class IndicatorNotFoundError(IndicatorAdapterError):
    """Raised when a requested indicator is not present in feature data."""


class IndicatorValidationError(IndicatorAdapterError):
    """Raised when feature input cannot be used by the adapter."""
