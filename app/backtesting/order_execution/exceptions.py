"""Order execution exceptions."""

from __future__ import annotations


class OrderExecutionError(Exception):
    """Base error for simulated order execution."""


class OrderRejectedError(OrderExecutionError, ValueError):
    """Order violated trading rules or insufficient cash."""


class OrderConfigurationError(OrderExecutionError, ValueError):
    """Invalid execution configuration."""
