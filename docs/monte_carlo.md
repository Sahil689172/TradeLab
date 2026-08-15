# TradeLab Monte Carlo (A5.6)

Monte Carlo in TradeLab answers:

> Given the **completed trades** from a historical backtest, how sensitive are
> equity, return, and drawdown to **trade order** and **resampling** of that
> observed P&L list?

It does **not** prove future profitability and it does **not** create new
independent market observations.

## Canonical inputs

| Field | Source |
|-------|--------|
| Trades | A5.2 `ClosedTradeRecord` (`net_profit`, already net of brokerage and slippage) |
| Capital | `--initial-capital` / execution config |
| Open lots | Ignored until they are closed (replay-end force-close **is** a completed trade) |

Randomization happens **after** trade generation. The original trade list is
copied; historical P&L is not rewritten.

## Shuffle vs bootstrap

**TRADE_SHUFFLE (`--method shuffle`)**  
Permute the historical trade order. Each trade’s rupee `net_profit` is unchanged.
Because P&L is applied **additively**, **final capital is the same in every
shuffle**. Drawdown, minimum equity, and streaks **do** change. This isolates
path / ordering risk, not a new edge.

**BOOTSTRAP (`--method bootstrap`)**  
Sample the observed P&L list **with replacement**, keeping the same trade count.
A simulation may repeat a large winner or omit it. This describes the empirical
trade distribution — it is **not** a forecast of future trades.

Unsupported names (`PARAMETRIC`, `BLOCK_BOOTSTRAP`) are not implemented as fake
live methods.

## What it can tell us

- Distribution of final capital / return **under resampling of this sample**
- Ordering impact on drawdown (shuffle)
- Probability that a resampled path loses money or breaches a **documented**
  ruin floor
- Whether a few trades dominate outcomes
- Sensitivity of those probabilities to alternate slippage assumptions

## What it cannot tell us

- Whether the strategy will be profitable next year
- Independent observations: 10,000 simulations of 4 trades are still 4 trades
- Path-dependent share sizing (A5.2 sizes from cash at entry; MC adds rupee P&L)
- Intrabar look-ahead (it never sees candles)

## Small samples

If only 2, 4, or 10 historical trades exist, the engine **warns** and **caps**
robustness. Simulation count does not increase sample size.

## Percentiles

Return and capital percentiles are the usual increasing distribution
(P01 = left tail).

Max drawdown is stored as `equity / peak - 1` (negative). The report also shows
**magnitude** percentiles where **P99 is more severe**.

## Risk of ruin

Ruin is **not** a universal industry constant. In TradeLab it means:

> Simulated equity fell below `--ruin-threshold` at any point on that path.

`--ruin-threshold 0.5` means 50% of initial capital. A value `> 1` is treated as
an absolute rupee floor. Additive P&L often never hits zero if total losses are
smaller than capital — that is not “safe”, only “this sample cannot reach 0”.

## Execution-cost sensitivity

Optional. Does **not** change the canonical backtest. It rebuilds `net_profit`
from `gross_profit` under alternate slippage (and optional commission multiplier)
on a **copy**, then re-runs the same sampler/seed.

## Robustness score

Transparent deductions from 100 (see `app/backtesting/monte_carlo/robustness.py`).
**HIGH** requires score ≥ 70, at least 10 trades, P(loss) < 20%, P95 \|DD\| < 25%,
and **median return > 0**. A profitable median alone is never enough.

## Reproducibility

`numpy` Generator, `--seed`. Same trades + config + seed → same JSON summaries.

## Examples

```bat
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --trades-json tests\fixtures\monte_carlo_trades.json --method shuffle --simulations 200 --seed 42 --initial-capital 10000
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --symbol RELIANCE --strategy ema_trend --method bootstrap --simulations 10000 --seed 42 --cost-sensitivity
```
