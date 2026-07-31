"""Exceptions raised by the levels engine."""

from __future__ import annotations


class LevelsError(Exception):
    """Base error for levels engine failures."""


class LevelsValidationError(LevelsError):
    """Raised when OHLCV input cannot support level computation."""
