# Universe Strategy Validation (A4.14)

Validates that every registered strategy **executes** and emits a valid
`TradeRecommendation` for every available OHLCV symbol.

This is **not** a backtest — no PnL, equity curves, or fills.

## Architecture

| Module | Role |
|--------|------|
| `discovery` | Find `SYMBOL.parquet`, ignore `*_features.parquet` |
| `loaders` | Merge OHLCV + features into a strategy frame |
| `engine` | Parallel per-symbol validation via `ThreadPoolExecutor` |
| `aggregation` | Per-strategy and per-stock statistics |
| `reports` | Console / JSON / CSV writers |

Reuses `StrategyValidationFramework` + `StrategyContextProvider` — no duplicated
`bind_*` logic.

## CLI

```bash
python backend/scripts/validate_universe.py
python backend/scripts/validate_universe.py --symbol RELIANCE --strategy all
python backend/scripts/validate_universe.py --symbol TCS --strategy ema_trend
python backend/scripts/validate_universe.py --limit 10 --workers 4
```

Reports:

- `backend/data/logs/universe_validation.json`
- `backend/data/logs/universe_validation.csv`
