# Relative Strength Strategy

**Module:** `app/strategies/relative_strength/`  
**Strategy name:** `relative_strength`

Cross-sectional strength vs the **NIFTY500** universe and a **NIFTY50** benchmark.  
This is **not** RSI.

---

## Package layout

| File | Role |
|------|------|
| `scoring.py` | Batch 3m/6m/12m returns, RS vs benchmark, momentum, sector strength |
| `ranking.py` | Universe rank, Top 10/25/50/100, percentile cuts |
| `screener.py` | Screener: top / worst / improving / weakening |
| `strategy.py` | BUY/SELL TradePlan with EMA + volume + VWAP filters |
| `schemas.py` | Score, RankedSymbol, UniverseRanking, ScreenerResult, Plan |

---

## Batch scoring (NIFTY500-ready)

```python
from app.strategies.relative_strength import RelativeStrengthScreener, RelativeStrengthConfig

screener = RelativeStrengthScreener(RelativeStrengthConfig())
result = screener.rank_frames(stock_frames, nifty50_frame)
# result.top_ranked, worst_ranked, fastest_improving, fastest_weakening
# result.ranking.top_10 / top_25 / top_50 / top_100 / strongest
```

From Feature Store:

```python
result = screener.rank_repository(nifty500_symbols, feature_repository)
```

---

## BUY

Stock in **top 20%** of RS rank **and** EMA trend bullish **and** volume healthy  
**and** close above VWAP.

## SELL

Rank falls below configurable band (`sell_rank_percentile`, default top 40% cut).

---

## TradePlan fields

Current Rank · Previous Rank · Strength Score · Benchmark Comparison ·  
Sector Comparison · Momentum Score · Confidence · Reasons

---

## Screener deliverable

| List | Meaning |
|------|---------|
| Top ranked | Highest strength_score |
| Worst ranked | Lowest strength_score |
| Fastest improving | Largest positive rank_change |
| Fastest weakening | Largest negative rank_change |

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_relative_strength.py
```
