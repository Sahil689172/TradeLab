# Phase A4Y.1.5 — Professional EMA Evaluation

Statistical validation of **Raw EMA** vs **Professional EMA** without changing strategy code.

## Run

```bat
.venv\Scripts\python.exe backend\scripts\evaluate_ema_professional.py --symbol RELIANCE --synthetic
.venv\Scripts\python.exe backend\scripts\evaluate_ema_professional.py --limit 50 --synthetic
.venv\Scripts\python.exe backend\scripts\evaluate_ema_professional.py --all --synthetic
```

Identical execution settings for both modes: capital, brokerage, slippage, position %, stride.

## Outputs

Written under `backend/data/evaluation/`:

- `evaluation_report.json` / `.md`
- `metrics_comparison.csv`
- `filter_effectiveness.csv`
- `trades_raw.csv` / `trades_professional.csv`
- `executive_summary.md`
- `charts/*.png`

## Package

`app/backtesting/evaluation/` — metrics, lightweight backtester, statistics, charts, reports.
