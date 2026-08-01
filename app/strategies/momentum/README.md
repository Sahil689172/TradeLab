# Momentum Strategy

**Module:** `app/strategies/momentum/`  
**Strategy name:** `momentum`

Quantitative momentum from **historical returns and trend persistence**.  
This is **not** RSI.

---

## Reusable Momentum Engine

```python
from app.strategies.momentum import MomentumEngine, MomentumConfig, rank_scores

engine = MomentumEngine(MomentumConfig())
scores = engine.score(stock_frames, benchmark_frame=nifty50)
ranking = rank_scores(scores, top_percentile=0.20)
# ranking.portfolio  → top sleeve for portfolio construction
```

AI strategies and portfolio optimizers should consume `MomentumScore` /
`MomentumEngine` — do not reimplement return windows.

Batch close-matrix math is shared with Relative Strength (`period_return`,
`build_close_matrix`, `batch_period_returns`).

---

## Metrics

| Metric | Definition |
|--------|------------|
| 1m / 3m / 6m / 12m return | Simple close-to-close returns |
| Momentum score | Weighted blend of the four windows |
| Acceleration | 1m return − 3m return |
| Persistence | Fraction of windows with positive return |
| Relative strength | Stock 6m − benchmark 6m |

---

## BUY

Top momentum sleeve **and** EMA bullish **and** RS > threshold **and** above VWAP  
**and** volume healthy.

## SELL

Momentum score below threshold **or** EMA trend turns bearish.

---

## TradePlan

Momentum Score · Relative Strength · Momentum Rank · Entry · Stops/Targets ·  
Holding Estimate · Confidence · Reasons

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_momentum_strategy.py
```
