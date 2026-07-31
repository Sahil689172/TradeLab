"""Exceptions raised by the market structure engine."""

from __future__ import annotations


class MarketStructureError(Exception):
    """Base error for market structure analysis failures."""


class MarketStructureValidationError(MarketStructureError):
    """Raised when OHLCV input fails structural prerequisites."""
