# Trade Recommendation & Strategy Validation Engine

**Package:** `app/services/trade_recommendation/`

Final output layer for every TradeLab strategy. Downstream systems
(Backtesting, Monte Carlo, Paper, Live, Frontend, AI) must consume **only**
`TradeRecommendation` objects — never raw strategy `TradePlan`s.

---

## Symbol propagation

Feature frames carry the trading symbol in ``attrs["symbol"]`` (or a ``symbol``
column). ``StrategyRunner`` binds that value onto the strategy before
``validate`` / ``prepare`` / signal / plan. Concrete strategies emit
``self.active_symbol`` on ``Signal`` and ``TradePlan`` — never a hardcoded
default. The recommendation engine copies ``plan.symbol`` unchanged.

## Strategy feature frames

``FeaturePipeline`` emits **OHLCV + indicators**. Legacy ``*_features.parquet``
files that only stored indicators are joined with ``SYMBOL.parquet`` via
``load_strategy_features`` / ``merge_ohlcv_features`` before validation.

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

## Strategy Context Provider

```python
from app.services.strategy_context import StrategyContextProvider

provider = StrategyContextProvider()
context = provider.prepare(strategy, "RELIANCE")
plan = strategy.execute(context)
```

The provider is the only place that prepares daily data, levels, structure, VWAP/RVOL,
and RS/momentum rankings. Validators must not call ``bind_daily`` / ``bind_levels`` /
``bind_ranking`` manually.

---

## Strategy Validation + CLI

Context for each strategy (daily OHLCV, levels, rankings, VWAP/RVOL) is prepared by
``StrategyContextProvider`` — the validator does not call ``bind_*`` manually.

```bash
python backend/scripts/validate_strategies.py --strategy all --symbol RELIANCE
python backend/scripts/validate_strategies.py --strategy ema --symbol RELIANCE
```

Produces a validation table: status, signal counts, avg confidence/holding, errors.
