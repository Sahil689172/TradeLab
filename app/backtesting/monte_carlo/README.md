# Monte Carlo Robustness Engine (Phase A5.6)

Post-trade resampling of **completed** historical trades. This package does not
rewrite A5.1 replay, A5.2 execution, or A5.3 position management.

**Monte Carlo simulations resample historical evidence; they do not create new
independent historical observations.**

## Architecture

```text
MonteCarloEngine                    # facade
    ├── TradeResamplingMonteCarlo   # A5.6 (default)
    │     ├── shuffle
    │     ├── bootstrap
    │     └── block_bootstrap
    └── PathDependentMonteCarlo     # A5.7 PathDependentPortfolioMonteCarlo
          resampled historical prices
          → A5.2 sizing from current cash
          → A5.2 slippage / brokerage
          → updated equity
```

A5.6 adds historical rupee `net_profit`. A5.7 does **not**. It reallocates a
fraction of **current cash** to each resampled trade's entry/exit prices.

**Monte Carlo simulations resample historical evidence; they do not create new
independent historical observations.**

Full candle-level path Monte Carlo (Strategy → Signal → Execution → Position
Manager) is still not implemented.

## Canonical inputs

| Item | Canonical source |
|------|------------------|
| Completed trades | A5.2 `ClosedTradeRecord` (`ExecutionResult.trade_log`) |
| P&L | `net_profit` = gross − brokerage − slippage (costs **already included**) |
| Returns | `net_profit / (quantity * entry_price)` when notional is valid |
| Open trades | **Excluded** until closed (replay-end force-close **is** a completed trade) |

Randomization is **trade order** (shuffle) or **trade selection** (bootstrap /
block bootstrap). P&L values and position sizes are **not** randomized.

## Capital modes (not interchangeable)

`ADDITIVE_PNL` (default, existing mode):

```text
equity[t] = equity[t-1] + trade_net_profit[t]
```

`RETURN_BASED` (only if every trade has a valid notional/return):

```text
equity[t] = equity[t-1] * (1 + return[t])
```

If return data is unavailable, the engine stays in `ADDITIVE_PNL` and reports
the fallback. Every JSON result includes `capital_mode`.

## Configuration

| Field | Meaning |
|-------|---------|
| `simulations` | Number of resampled paths (1 … 1,000,000) |
| `random_seed` | Dedicated `numpy.random.Generator` seed |
| `sampling_method` | `shuffle` / `bootstrap` / `block_bootstrap` |
| `capital_mode` | `ADDITIVE_PNL` / `RETURN_BASED` |
| `block_size` | Block length for block bootstrap (capped at trade count) |
| `engine_mode` | `trade_resampling` (A5.6) or `path_dependent` (A5.7) |
| `sizing_mode` | A5.7: `percent_of_equity` / `fixed_fractional` / `fixed_cash` |
| `position_percent` | A5.7 fraction of current cash (e.g. 10 = 10%) |
| `ruin_threshold` | ≤1 = fraction of initial capital; >1 = rupee floor |
| `include_cost_perturbation` | A5.6 reconstructs net from gross; A5.7 re-simulates with alternate slippage |

## Report

The report separates historical observation, Monte Carlo setup, percentile
distribution, risk, sample quality, and a sample-capped **verdict**
(`INSUFFICIENT_EVIDENCE` / `WEAK` / `LIMITED` / `PROMISING` / `ROBUST`).

Percentiles are **Monte Carlo percentile intervals** (`numpy.percentile`,
`method='linear'`), not statistical confidence intervals.

## CLI

```bat
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --symbol RELIANCE --strategy ema_trend --method bootstrap --simulations 10000 --seed 42
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --trades-json logs\trade_log.json --method shuffle --seed 42
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --synthetic-trades 100 --simulations 10000 --seed 42 --benchmark
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --trades-json tests\fixtures\monte_carlo_trades.json --mode path_dependent --position-percent 10 --simulations 10000 --seed 42 --cost-sensitivity --compare-a56
```
