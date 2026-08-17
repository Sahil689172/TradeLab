"""A7 portfolio allocation exceptions."""

from __future__ import annotations


class PortfolioAllocationError(Exception):
    """Base class for portfolio allocation failures."""


class AllocationError(PortfolioAllocationError, ValueError):
    """Invalid allocation request (bad method, missing inputs, no symbols)."""
