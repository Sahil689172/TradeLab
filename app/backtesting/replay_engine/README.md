# Historical Replay Engine (Phase A5.1)

Feeds historical OHLCV **candle-by-candle** into the existing Strategy Engine
with **zero look-ahead bias**. No orders, portfolio, or PnL.

> Package path: `app/backtesting/replay_engine/` (TradeLab convention).  
> There is no `backend/app/` package in this repository.

## Guarantee

At cursor index `i`, strategies only see `frame.iloc[: i + 1]`  
(all timestamps ≤ current candle). Future rows are never passed.

## Components

| Module | Role |
|--------|------|
| `replay_session.py` | Cursor, window, status |
| `scheduler.py` | `fast` / `realtime` pacing |
| `events.py` | ReplayStarted, NewCandle, StrategyEvaluation, RecommendationGenerated, ReplayCompleted |
| `engine.py` | Orchestration |
| `adapters.py` | Market data, features, context evaluator DI |
| `protocols.py` | Ports for injection |

## CLI

```bat
.venv\Scripts\python.exe backend\scripts\replay_backtest.py --symbol RELIANCE --speed fast
.venv\Scripts\python.exe backend\scripts\replay_backtest.py --symbol RELIANCE --start-date 2022-01-01 --end-date 2022-12-31 --speed fast
```

## Integration

Reuses unchanged:

- Parquet OHLCV / features
- `StrategyContextProvider`
- Strategy Engine (`strategy.execute`)
- `TradeRecommendationEngine`

Each `ReplayStepResult` now also carries optional `current_open` / `current_high`
/ `current_low` so A5.3 can detect stops/targets without look-ahead. Close-only
construction remains valid (high/low default to close).

Position tracking after fills: `app/backtesting/position_manager/`.
