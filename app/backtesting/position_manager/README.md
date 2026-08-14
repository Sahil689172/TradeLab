# Position Manager (Phase A5.3)

Tracks the **lifecycle of an individual position** after the Order Execution
Engine fills or rejects an order. It does **not** decide whether a trade should
be opened.

> Package path: `app/backtesting/position_manager/`  
> Broker lots remain `PositionState` in A5.2. Do not duplicate cash, brokerage,
> or slippage here.

## Responsibilities

| Layer | Decides |
|-------|---------|
| Strategy | `BUY` / `SELL` / `HOLD` / `EXIT` |
| Execution Engine | Whether an order can fill (cash, duplicate, no position, …) |
| Position Manager | Position state after fills: qty, prices, P&L, stops/targets, status |

```
Strategy → Recommendation → Order → Execution Engine
                                      ↓ FILLED / REJECTED
                               Position Manager
                                      ↓
                               Position State
                                      ↓
                     Future Portfolio / Risk / Performance
```

## Signal vs order vs fill vs position vs trade

| Term | Meaning |
|------|---------|
| Signal | Strategy output (`BUY`/`SELL`/`HOLD`/`EXIT`) |
| Recommendation | Validated `TradeRecommendation` (entry, stop, T1, T2) |
| Order | Simulated `MarketOrder` submitted to the broker |
| Fill | Broker execution at slippage-adjusted price |
| Position | Open (or closed-history) lot tracked by this manager |
| Trade | Round-trip in A5.2 `ClosedTradeRecord` / `trade_log` |

A **BUY recommendation does not open a position**. Only a **FILLED BUY** does.
A **REJECTED BUY** leaves position state unchanged.

## Lifecycle

```
NO_POSITION
     ↓
BUY FILLED
     ↓
OPEN
 ┌───┼──────────────┐
 ↓   ↓              ↓
T1  T2           STOP LOSS
 ↓   ↓              ↓
OPEN CLOSED*      CLOSED
       ↑
       │
STRATEGY EXIT / SELL / END_OF_BACKTEST
       │
       ↓
    CLOSED
```

\* Target 1 / target 2 are **flags** by default. Hitting T1 or T2 does **not**
close the full position (reserved for future scaling). Stop-loss **does**
request an EXIT through the existing execution engine.

Statuses: `OPEN`, `PARTIALLY_CLOSED` (extension point), `CLOSED`, `CANCELLED`.

## Opening

```
Recommendation BUY RELIANCE qty=10 price=1200
Order BUY → Execution FILLED
Position Manager: OPEN RELIANCE qty=10 entry_price=1200 (fill price)
```

Rejected BUY → no position.

Duplicate BUY while long (no pyramiding): `ALREADY_POSITIONED`
(maps from A5.2 `Already holding position`).

SELL with no open lot: `NO_OPEN_POSITION` (no short, no cash mutation here).

## Updates (mark-to-market)

On each historical candle, using **only that candle's OHLC**:

- `current_price` ← close
- `unrealized_pnl` ← `(current_price - entry_price) * quantity`
- `holding_period` ← now − entry
- `entry_price` is immutable

Transaction costs stay in the execution engine. Unrealized P&L is the gross
mark. Realized P&L on close uses `Fill.realized_pnl` (net of brokerage/slippage).

## Stop-loss and targets

Long stop: `low <= stop_loss` (gap-through: `open <= stop_loss` fills at open).

Same-bar as entry is **not** used for stop/target checks (entry is at close;
using that bar's low/high would look ahead intra-bar).

On stop: emit `STOP_LOSS_TRIGGERED`, then `ReplayPositionRunner` submits `EXIT`
through `OrderExecutionEngine`. There is no second broker.

On target 1 / 2: set `target_*_hit` (+ timestamp). Position stays `OPEN`.

Same-bar stop and target: **stop wins**.

## Exit / close

| Reason | When |
|--------|------|
| `STRATEGY_EXIT` | Strategy `EXIT` fill |
| `STRATEGY_SELL` | Strategy `SELL` fill |
| `STOP_LOSS` | Protective stop fill via execution |
| `TARGET_2` | Only if an exit fill is inferred as T2 (not auto-closed) |
| `END_OF_BACKTEST` | `FORCE_CLOSE` policy |
| `MANUAL` | Test / explicit close |

Closed records are **kept** in history. They do not keep accumulating unrealized P&L.

## End-of-backtest policy

Configurable, never silent:

| Policy | Default | Behaviour |
|--------|---------|-----------|
| `FORCE_CLOSE` | **yes** | Flatten at last close, `exit_reason=END_OF_BACKTEST` |
| `MARK_TO_MARKET` | | Leave open; refresh unrealized P&L |
| `LEAVE_OPEN` | | Leave open; do not force a close |

A5.2 `close_open_at_replay_end` is unchanged when you call
`OrderExecutionEngine.process_replay_result` without the Position Manager.
`ReplayPositionRunner` applies the A5.3 policy instead.

## Partial fills

A5.2 market orders fill in full. `apply_fill` uses `fill.quantity`. If a future
partial SELL arrives with `qty < position.qty`, status becomes `PARTIALLY_CLOSED`.
No partial-fill engine is invented here.

## Multiple symbols

One open long per symbol. `RELIANCE` / `TCS` / `HDFCBANK` / `INFY` never share
state. Capital allocation is **not** this phase (A5.4).

## Integration

```python
from app.backtesting.order_execution import ExecutionConfig, OrderExecutionEngine
from app.backtesting.position_manager import (
    PositionManager,
    PositionManagerConfig,
    ReplayPositionRunner,
)

engine = OrderExecutionEngine(ExecutionConfig(initial_capital=10_000, ...))
pm = PositionManager()
runner = ReplayPositionRunner(engine, pm)
exec_result, pos_result = runner.process_replay(replay_result)
```

CLI (implies order execution):

```bat
.venv\Scripts\python.exe backend\scripts\replay_backtest.py --symbol RELIANCE --execute-orders --track-positions
```

## Observability

Lifecycle events (`POSITION_OPENED`, `TARGET_1_HIT`, `STOP_LOSS_TRIGGERED`, …)
are stored on the manager. `POSITION_UPDATED` is debug-level so large-universe
replays stay quiet. Enable `PositionManagerConfig(debug=True)` for verbose lines.
