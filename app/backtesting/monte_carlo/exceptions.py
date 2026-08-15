"""Monte Carlo errors — fail loudly on invalid inputs."""

from __future__ import annotations


class MonteCarloError(Exception):
    """Base error for A5.6."""


class MonteCarloDataError(MonteCarloError, ValueError):
    """Trade P&L or return series is not finite / not usable."""


class MonteCarloConfigError(MonteCarloError, ValueError):
    """Configuration cannot be simulated."""


class PathDependentNotImplementedError(MonteCarloError, NotImplementedError):
    """Path-dependent full-pipeline Monte Carlo is a future extension."""
