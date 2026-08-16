"""Walk-forward validation errors."""

from __future__ import annotations


class WalkForwardError(Exception):
    """Base error for A5.9."""


class WalkForwardConfigError(WalkForwardError, ValueError):
    """Invalid walk-forward specification."""


class WalkForwardLeakageError(WalkForwardError):
    """Train/test isolation was violated."""
