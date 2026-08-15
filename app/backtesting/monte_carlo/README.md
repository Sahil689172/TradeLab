# Monte Carlo Robustness Engine (Phase A5.6)

Post-trade resampling of **completed** historical trades. This package does not
rewrite A5.1 replay, A5.2 execution, or A5.3 position management.

## Implementation note (audit)

| Item | Canonical source |
|------|------------------|
| Completed trades | A5.2 `ClosedTradeRecord` (`ExecutionResult.trade_log`) |
| P&L | `net_profit` = gross − brokerage − slippage (costs **already included**) |
| Entry / exit | `entry_price`, `exit_price`, `entry_timestamp`, `exit_timestamp` |
| Initial capital | `ExecutionConfig.initial_capital` / CLI `--initial-capital` |
| Open trades | **Excluded**. Only closed round-trips (including A5.2 replay-end force-close) |
| Evaluation `EvalTrade` | Same field names; accepted via adapter for A4Y reports |
| A5.3 `Position` | Closed positions only; `realized_pnl` is the net fill P&L |

Shuffle applies the **same rupee P&L list** in a new order (path risk, not a new
sum). Bootstrap resamples that list **with replacement**. Neither is a forecast.

## CLI

```bat
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --symbol RELIANCE --strategy ema_trend --method bootstrap --simulations 10000 --seed 42
.venv\Scripts\python.exe backend\scripts\monte_carlo.py --trades-json logs\trade_log.json --method shuffle --seed 42
```
