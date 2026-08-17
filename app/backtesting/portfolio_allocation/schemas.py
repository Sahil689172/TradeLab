"""A7 portfolio capital-allocation schemas.

This layer decides *how much capital each symbol receives* before trading. It is
portfolio construction, not strategy optimization. Allocation weights are
estimated from historical (training) inputs only; out-of-sample outcomes never
feed back into weight construction.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


ALLOCATION_LIMITATION = (
    "Portfolio allocation splits a fixed capital budget across symbols using "
    "training-window estimates only (equal weight, inverse volatility, or "
    "equal-risk-contribution). It does not forecast returns, does not use "
    "out-of-sample data, and does not guarantee diversification benefits."
)


class AllocationMethod(str, Enum):
    """Supported capital-allocation methods."""

    EQUAL_WEIGHT = "equal_weight"
    INVERSE_VOLATILITY = "inverse_volatility"
    RISK_PARITY = "risk_parity"


class AllocationConstraints(BaseModel):
    """Hard limits applied to any allocation, regardless of method."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_capital: float = Field(default=1_000_000.0, gt=0.0)
    max_position_weight: float = Field(default=1.0, gt=0.0, le=1.0)
    max_symbol_exposure: float = Field(default=1.0, gt=0.0, le=1.0)
    max_concurrent_positions: int | None = Field(default=None, ge=1)
    min_allocation_weight: float = Field(default=0.0, ge=0.0, lt=1.0)
    cash_reserve_pct: float = Field(default=0.0, ge=0.0, lt=1.0)

    @property
    def effective_weight_cap(self) -> float:
        """Binding per-symbol weight cap (smaller of the two configured caps)."""
        return min(self.max_position_weight, self.max_symbol_exposure)


class SymbolAllocation(BaseModel):
    """Capital assigned to a single symbol."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    weight: float = Field(..., ge=0.0)
    capital: float = Field(..., ge=0.0)
    volatility: float | None = None
    capped: bool = False


class AllocationResult(BaseModel):
    """Deterministic output of the allocation layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: AllocationMethod
    total_capital: float
    cash_reserve_pct: float
    cash_reserve: float
    investable_capital: float
    allocated_capital: float
    unallocated_capital: float
    allocations: list[SymbolAllocation] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    capital_by_symbol: dict[str, float] = Field(default_factory=dict)
    dropped_symbols: list[str] = Field(default_factory=list)
    constraints: AllocationConstraints
    notes: list[str] = Field(default_factory=list)
    limitation: str = ALLOCATION_LIMITATION

    @model_validator(mode="after")
    def _no_over_allocation(self) -> "AllocationResult":
        # Capital conservation: allocated + cash must never exceed the budget.
        cash = self.total_capital - self.allocated_capital
        if self.allocated_capital > self.total_capital + 1e-6:
            raise ValueError("allocated capital exceeds total capital")
        if cash < -1e-6:
            raise ValueError("negative residual cash implies over-allocation")
        return self


class PortfolioMetrics(BaseModel):
    """Portfolio-level performance computed from per-symbol equity/P&L."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float
    final_equity: float
    total_return: float
    volatility: float
    max_drawdown: float
    sharpe: float
    sortino: float
    average_exposure: float
    concentration_hhi: float
    per_symbol_pnl: dict[str, float] = Field(default_factory=dict)
    per_symbol_contribution: dict[str, float] = Field(default_factory=dict)
    per_symbol_return: dict[str, float] = Field(default_factory=dict)
    symbol_count: int = 0
