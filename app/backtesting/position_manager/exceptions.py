"""Position Manager errors — fail loudly rather than corrupt state."""

from __future__ import annotations


class PositionManagerError(Exception):
    """Base error for position lifecycle tracking."""


class PositionInvariantError(PositionManagerError, ValueError):
    """A position violated a hard lifecycle invariant."""


class PositionLookAheadError(PositionManagerError, ValueError):
    """A bar or fill timestamp is earlier than the position's known history."""
