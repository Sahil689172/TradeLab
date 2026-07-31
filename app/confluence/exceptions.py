"""Exceptions raised by the confluence engine."""

from __future__ import annotations


class ConfluenceError(Exception):
    """Base error for confluence evaluation failures."""


class ConfluenceValidationError(ConfluenceError):
    """Raised when confluence inputs or configuration are invalid."""
