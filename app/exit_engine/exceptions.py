"""Exceptions raised by the exit engine."""

from __future__ import annotations


class ExitEngineError(Exception):
    """Base error for exit engine failures."""


class ExitValidationError(ExitEngineError):
    """Raised when exit inputs are incomplete or inconsistent."""
