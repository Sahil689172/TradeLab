# Portfolio Allocation (A7)

Portfolio-level **capital allocation** across symbols. This layer decides *how
much capital each symbol receives* before trading. It is portfolio construction,
**not** strategy optimization — it never tunes strategy parameters or loosens
filters.

It reuses the existing metric primitives (`evaluation.metrics`) and composes with
the multi-symbol walk-forward (`walk_forward.portfolio.symbol_allocation_capital`)
and Monte Carlo risk metrics. It adds no new third-party dependencies.

## Allocation methods

| Method | Weight rule |
|--------|-------------|
| `equal_weight` | `1 / n` per symbol (baseline) |
| `inverse_volatility` | `w_i ∝ 1 / σ_i` (train-window volatility) |
| `risk_parity` | equal risk contribution via a deterministic multiplicative fixed point; with a diagonal covariance this reduces to inverse volatility |

## Constraints (`AllocationConstraints`)

- `total_capital` — budget to split
- `max_position_weight` — cap on any single weight
- `max_symbol_exposure` — cap on total exposure to a symbol
- `max_concurrent_positions` — keep only the top-N by weight (ties broken by name)
- `min_allocation_weight` — drop symbols below the floor, then renormalize
- `cash_reserve_pct` — reserve un-invested cash off the top

Capping redistributes excess to uncapped symbols (water-filling). If the caps
bind every symbol, the remainder is left as extra cash — the layer **never
over-allocates**: `allocated_capital + residual_cash == total_capital`.

## Portfolio metrics (`portfolio_metrics`)

Equity, return, volatility, max drawdown, Sharpe, Sortino, exposure,
concentration (HHI), and per-symbol P&L contribution / per-symbol return.

## Leakage rule

```text
TRAIN → estimate allocation weights → FREEZE → OOS → evaluate
```

Weights are estimated from **training-window** returns / volatilities only.
Out-of-sample returns, future volatility, future correlations, and future trade
outcomes never enter weight construction. All functions are pure and
deterministic — same inputs produce identical allocations (no RNG).

## Example

```python
from app.backtesting.portfolio_allocation import (
    AllocationConstraints, AllocationMethod, allocate, portfolio_metrics,
)

result = allocate(
    AllocationMethod.RISK_PARITY,
    ["RELIANCE", "TCS", "INFY"],
    returns_by_symbol=train_returns,          # training window only
    constraints=AllocationConstraints(
        total_capital=1_000_000.0,
        max_position_weight=0.5,
        cash_reserve_pct=0.05,
    ),
)
# result.capital_by_symbol -> frozen allocation applied to the OOS window
```
