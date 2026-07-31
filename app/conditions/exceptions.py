"""Exceptions raised by the condition engine."""

from __future__ import annotations


class ConditionError(Exception):
    """Base error for condition evaluation failures."""


class ConditionValidationError(ConditionError):
    """Raised when a condition specification or context is invalid."""
