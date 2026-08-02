# Trade Recommendation & Strategy Validation Engine

**Package:** `app/services/trade_recommendation/`

Final output layer for every TradeLab strategy. Downstream systems
(Backtesting, Monte Carlo, Paper, Live, Frontend, AI) must consume **only**
`TradeRecommendation` objects — never raw strategy `TradePlan`s.

---

## Pipeline

```
TradePlan  →  Validate  →  Standardize  →  TradeRecommendation
```

```python
from app.services.trade_recommendation import TradeRecommendationEngine

engine = TradeRecommendationEngine()
rec = engine.recommend(plan, timeframe="15 Minute", detailed_plan=strategy.last_detailed_plan)
```

---

## Schema

`TradeRecommendation` includes: strategy, symbol, timeframe, timestamp, signal
(BUY/SELL/HOLD/EXIT), entry/stop/targets, RR, confidence (0–100), holding,
trend, market structure, indicators, reasons, warnings, trade_id.

---

## Validation

`TradeRecommendationValidator` enforces:

| Signal | Rules |
|--------|--------|
| BUY | SL < Entry, T1 > Entry, T2 > T1 |
| SELL | SL > Entry, T1 < Entry, T2 < T1 |
| All | positive prices, confidence 0–100, RR ≥ min, valid timestamp, unique trade_id |

---

## Aggregator

```python
from app.services.trade_recommendation import RecommendationAggregator

agg = RecommendationAggregator()
result = agg.aggregate([rec_ema, rec_vwap, rec_cpr, ...])
# result.consensus: STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL | EXIT
```

Conflict (BUY + SELL present) → **HOLD** with explanation.  
Strong agreement (count + confidence thresholds) → **STRONG_BUY / STRONG_SELL**.

---

## Confidence Engine

Weighted blend: strategy · trend · volume · structure · RR · confluence → 0–100.

---

## Reports

```python
from app.services.trade_recommendation import build_recommendation_report
print(build_recommendation_report(rec).body)
```

---

## Strategy Validation + CLI

```bash
python backend/scripts/validate_strategies.py --strategy all --symbol RELIANCE
python backend/scripts/validate_strategies.py --strategy ema --symbol RELIANCE
```

Produces a validation table: status, signal counts, avg confidence/holding, errors.
