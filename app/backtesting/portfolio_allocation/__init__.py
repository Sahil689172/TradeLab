"""A7 portfolio optimization / capital allocation layer.

Deterministic, leakage-safe capital allocation across symbols:

- equal-weight baseline
- inverse-volatility allocation
- equal-risk-contribution (risk parity)

with allocation constraints (total capital, per-symbol weight cap, symbol
exposure cap, max concurrent positions, minimum allocation, cash reserve) and
portfolio-level metrics (return, volatility, drawdown, Sharpe, Sortino,
exposure, concentration, per-symbol P&L contribution).

Allocation weights are estimated from training inputs only; out-of-sample data
never influences allocation.
"""

from app.backtesting.portfolio_allocation.allocator import (
    allocate,
    apply_constraints,
    compute_raw_weights,
    estimate_volatilities,
)
from app.backtesting.portfolio_allocation.exceptions import (
    AllocationError,
    PortfolioAllocationError,
)
from app.backtesting.portfolio_allocation.metrics import (
    herfindahl_index,
    portfolio_metrics,
)
from app.backtesting.portfolio_allocation.schemas import (
    ALLOCATION_LIMITATION,
    AllocationConstraints,
    AllocationMethod,
    AllocationResult,
    PortfolioMetrics,
    SymbolAllocation,
)

__all__ = [
    "ALLOCATION_LIMITATION",
    "AllocationConstraints",
    "AllocationError",
    "AllocationMethod",
    "AllocationResult",
    "PortfolioAllocationError",
    "PortfolioMetrics",
    "SymbolAllocation",
    "allocate",
    "apply_constraints",
    "compute_raw_weights",
    "estimate_volatilities",
    "herfindahl_index",
    "portfolio_metrics",
]
