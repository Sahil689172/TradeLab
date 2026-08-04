# Order Execution Engine (Phase A5.2)

Converts ``TradeRecommendation`` objects from the Replay Engine into simulated
market executions. **No portfolio analytics** — cash, positions, fills, and a
trade log only.

> Package path: ``app/backtesting/order_execution/`` (TradeLab convention).

## Rules

- Market orders only: ``BUY`` / ``SELL`` (``EXIT`` maps to ``SELL``)
- Cannot BUY while already holding the symbol
- Cannot SELL with no open position
- BUY size respects available cash (after brokerage estimate)
- Slippage + brokerage applied on every fill
- Every fill is appended to the trade log

## Integration

```
Replay Engine → TradeRecommendation → OrderExecutionEngine → Trade Log
```
