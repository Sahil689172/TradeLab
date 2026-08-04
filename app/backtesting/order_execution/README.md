# Order Execution Engine (Phase A5.2 / A5.2.1)

Converts ``TradeRecommendation`` objects from the Replay Engine into simulated
market executions. **No portfolio analytics** — cash, positions, fills,
rejection diagnostics, and trade logs only.

> Package path: ``app/backtesting/order_execution/`` (TradeLab convention).

## Rules

- Market orders only: ``BUY`` / ``SELL`` (``EXIT`` maps to ``SELL``)
- Cannot BUY while already holding the symbol
- Cannot SELL with no open position
- Whole shares only by default; qty < 1 →
  ``Capital insufficient to purchase one share.``
- BUY size respects available cash (after brokerage estimate)
- Slippage + brokerage applied on every fill
- Every fill is logged; closed round-trips go to ``trade_log``
- Every rejection is logged to ``rejected_orders``

## Position sizing (one mode at a time)

| Mode | CLI |
|------|-----|
| ``fixed_amount`` | ``--position-sizing fixed_amount --amount 500`` |
| ``fixed_quantity`` | ``--position-sizing fixed_quantity --quantity 3`` |
| ``percent_of_capital`` | ``--position-sizing percent_of_capital --percent 25`` |

## Integration

```
Replay Engine → TradeRecommendation → OrderExecutionEngine → Trade / Reject logs
```
