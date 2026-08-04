"""Order execution exceptions."""

from __future__ import annotations

from app.backtesting.order_execution.schemas import RejectionReason


class OrderExecutionError(Exception):
    """Base error for simulated order execution."""


class OrderRejectedError(OrderExecutionError, ValueError):
    """Order violated trading rules or insufficient cash."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: RejectionReason = RejectionReason.VALIDATION_FAILURE,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class OrderConfigurationError(OrderExecutionError, ValueError):
    """Invalid execution configuration."""
