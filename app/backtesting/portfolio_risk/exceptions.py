"""Portfolio-risk errors. Do not reuse these to change A5.2 fill semantics."""

from __future__ import annotations


class PortfolioRiskError(Exception):
    """Base error for A5.8."""


class PortfolioConfigError(PortfolioRiskError, ValueError):
    """Invalid portfolio-risk configuration."""


class PortfolioDataError(PortfolioRiskError, ValueError):
    """Trade data cannot be aggregated into a portfolio book."""
