# Walk-forward / out-of-sample validation (A5.9)

Orchestration layer. Does **not** replace A5.1 replay, A5.2 execution, A5.3
positions, A5.6 Monte Carlo, or A5.8 portfolio risk.

```text
Market Data (cached, date-capped)
    → WalkForwardEngine
        → train window (timestamp <= train_end)
            → declared candidate grid
            → A5.1 + A5.2 score on TRAIN only
            → freeze winner
        → test window (timestamp <= test_end; pre-test bars for indicator warmup)
            → frozen config, no re-optimization
        → roll
    → concatenate TEST trades only
    → optional A5.8 on OOS trades
    → optional OUT-OF-SAMPLE Monte Carlo on OOS trades
```

**Warmup vs leakage:** test execution may see candles **before** `test_start`
so EMA(200) is defined, but never candles **after** `test_end`. Training never
sees `timestamp > train_end`.

Walk-forward does not prove future profitability. Monte Carlo on OOS trades
does not create new independent historical observations.

Canonical equity curves use market timestamps only; see
`app/backtesting/walk_forward/equity.py`.
