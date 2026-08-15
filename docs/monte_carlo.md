# TradeLab Monte Carlo (A5.6)

Monte Carlo in TradeLab answers:

> Given the **completed trades** from a historical backtest, how sensitive are
> equity, return, and drawdown to **trade order** and **resampling** of that
> observed trade set?

**Monte Carlo simulations resample historical evidence; they do not create new
independent historical observations.**

This layer does **not** prove future profitability and it does **not** re-run
A5.1 replay, A5.2 order execution, or A5.3 position management inside each
simulation.

## Architecture

```text
MonteCarloEngine
    ├── TradeResamplingMonteCarlo     # implemented (A5.6)
    │     ├── Shuffle
    │     ├── Bootstrap
    │     └── BlockBootstrap
    └── PathDependentMonteCarlo       # FUTURE A5.x stub only
```

`PathDependentMonteCarlo` is an extension point for a later full pipeline
(Strategy → Signal → Order Execution → Position Manager → Portfolio → Equity).
It raises `PathDependentNotImplementedError` in this phase.

## Canonical inputs

| Field | Source |
|-------|--------|
| Trades | A5.2 `ClosedTradeRecord` (`net_profit`, already net of brokerage and slippage) |
| Gross vs net | `gross_profit` vs `net_profit`; costs are **already embedded** in net |
| Capital | `--initial-capital` / execution config |
| Open lots | Ignored until they are closed (replay-end force-close **is** a completed trade) |

Randomization happens **after** trade generation. The original trade list is
copied; historical P&L is not rewritten.

What is randomized:

| Method | Order | Selection | P&L values | Position sizes |
|--------|-------|-----------|------------|----------------|
| shuffle | yes | no (same multiset) | no | no |
| bootstrap | implied | yes, with replacement | no | no |
| block_bootstrap | block order | yes, blocks with replacement | no | no |

## Shuffle vs bootstrap vs block bootstrap

**TRADE_SHUFFLE (`--method shuffle`)**  
Permute the historical trade set. Each trade’s rupee `net_profit` (or return) is
unchanged. **No replacement.** The original multiset is preserved exactly.

Under `ADDITIVE_PNL`, **final capital is the same in every shuffle** because
addition is commutative. Drawdown, minimum equity, and streaks **do** change.
Under `RETURN_BASED`, the product of `(1+r)` is also commutative, so final
equity is likewise invariant; path risk still changes.

**BOOTSTRAP (`--method bootstrap`)**  
Sample the observed completed trades **independently with replacement**, keeping
the same trade count per simulation. A simulation may repeat a large winner or
omit it. This assumes historical trades are **representative**. It is **not** a
forecast of future trades.

**BLOCK_BOOTSTRAP (`--method block_bootstrap --block-size N`)**  
Sample overlapping **circular** blocks of length `N` with replacement, then
truncate to the original trade count. This preserves short serial dependence
without inventing a market-path model. `block_size` is capped at the trade
count.

## Capital modes (never mixed)

These modes are **not interchangeable**. Every result records `capital_mode`.

**ADDITIVE_PNL** (default; the original A5.6 mode):

```text
equity[t] = equity[t-1] + trade_net_profit[t]
```

Rupee P&L is applied additively. Equity may go negative if losses exceed
capital. This does **not** model path-dependent share counts from A5.2 sizing.

**RETURN_BASED** (`--capital-mode RETURN_BASED`):

```text
equity[t] = equity[t-1] * (1 + return[t])
```

Used only when every historical trade has a valid notional
(`quantity * entry_price > 0`) and therefore a usable `return_pct`.
`1 + return` is floored at 0 so equity cannot go negative. If return data is
unavailable, the engine **remains in ADDITIVE_PNL** and says so.

## Drawdown, ruin, Sharpe, percentiles

Every simulation produces an equity path (not stored by default).

| Metric | Definition |
|--------|------------|
| Ending equity | last point on the path |
| Net profit | ending equity − initial capital |
| Total return | net profit / initial capital |
| Max drawdown | `min_t (equity_t / running_peak_t − 1)` |
| Max drawdown % | same fraction |
| Volatility | sample std of per-trade step returns (`ddof=1`); 0 if fewer than 2 trades |
| Sharpe | mean step return / volatility (trade-level, **not annualized**); 0 if volatility is ~0 or n<2 |
| Losing / winning streak | longest consecutive negative / positive trades on that path |
| P(loss) | fraction of simulations with ending equity **<** initial capital |
| P(profit) | ending equity **>** initial capital |
| P(target return) | `P(total_return > threshold)` |
| P(drawdown > X) | `P(\|max DD\| > X)` |
| P(ruin) | fraction of simulations whose **minimum** equity is **<** the configured ruin floor |

Ruin is **not** a universal industry constant. `--ruin-threshold 0.5` means 50%
of initial capital. A value `> 1` is an absolute rupee floor. Additive P&L often
never hits zero if total losses are smaller than capital — that is not “safe”,
only “this sample cannot reach that floor”.

Percentiles P01…P99 use `numpy.percentile(..., method="linear")`. They are
**Monte Carlo percentile intervals**, not statistical confidence intervals.

## Transaction costs

Canonical `net_profit` already has brokerage and slippage subtracted. Monte
Carlo **does not apply those costs again**.

Cost sensitivity reconstructs:

```text
new_net = gross_pnl − new_brokerage − new_slippage
```

on a **copy**. Each sensitivity row reports `base_cost`, `scenario_cost`,
`incremental_cost`, and `final_simulated_pnl` (median simulated net profit).

## Small samples

| Historical trades | Sample quality (reporting label only) |
|-------------------|----------------------------------------|
| 0 | INVALID |
| 1–4 | EXTREMELY_LOW |
| 5–19 | LOW |
| 20–49 | LIMITED |
| 50–99 | MODERATE |
| 100+ | STRONGER |

These are **not** claims of statistical sufficiency. Example: 2 historical
trades and 10,000 simulations is still 2 trades:

> 10,000 simulations generated from 2 historical trades.

The report must not present that as “10,000 observations”.

## Verdict (not PASS/FAIL)

| Verdict | Meaning |
|---------|---------|
| INSUFFICIENT_EVIDENCE | Too little historical evidence (always for 0–4 trades) |
| WEAK | Weak distribution and/or small sample (max for 5–19 trades) |
| LIMITED | Mixed evidence (max for 20–49 trades) |
| PROMISING | Favorable distribution (max for 50–99 trades) |
| ROBUST | Favorable distribution **and** ≥100 historical trades |

A tiny sample with an excellent simulated distribution is still
`INSUFFICIENT_EVIDENCE`. Simulations cannot manufacture independent history.

The older HIGH/MEDIUM/LOW robustness **band** remains as a diagnostic score.
It is not the verdict.

## Reproducibility

Dedicated `numpy.random.Generator`. Same trades + same configuration + same
seed → identical summaries. A different seed produces different resampled
paths. JSON records `seed`, `simulation_count`, `method`, `capital_mode`,
`trade_count`, and related configuration. JSON is written with `sort_keys=True`
and `allow_nan=False`.

## Validation

Before simulation the engine rejects non-finite P&L/returns, requires
`initial_capital > 0`, `simulations > 0`, `ruin_threshold > 0`, and validates
percentile configuration. Closed trades with `entry_timestamp > exit_timestamp`
are rejected.

## CLI

```bat
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --trades-json tests\fixtures\monte_carlo_trades.json --method shuffle --simulations 200 --seed 42 --initial-capital 10000
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --symbol RELIANCE --strategy ema_trend --method bootstrap --simulations 10000 --seed 42 --cost-sensitivity --capital-mode ADDITIVE_PNL
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --synthetic-trades 100 --simulations 10000 --seed 42 --benchmark --output backend\data\monte_carlo\bench_10k
```

Outputs: `backend/data/monte_carlo/<stem>_monte_carlo.json|.md|.csv`.
