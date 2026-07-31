"""Exceptions raised by the risk engine."""

from __future__ import annotations


class RiskEngineError(Exception):
    """Base error for risk engine failures."""


class RiskValidationError(RiskEngineError):
    """Raised when risk inputs are incomplete or inconsistent."""
