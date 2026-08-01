# SuperTrend Strategy

**Module:** `app/strategies/supertrend/`  
**Strategy name:** `supertrend`  
**Indicator service:** `app/services/strategy_engine/indicators/supertrend.py`

Standalone trend-flip strategy backed by a **reusable SuperTrend service** —
Exit Engine, Confluence, Strategy Builder, and AI strategies should inject
`SuperTrendService` / `compute_supertrend` rather than reimplementing the math.

Defaults: **ATR period = 10**, **multiplier = 3**.

---

## Reusable indicator

```python
from app.services.strategy_engine.indicators import SuperTrendService
from app.indicator_adapter import IndicatorAdapter

service = SuperTrendService(atr_period=10, multiplier=3.0)
frame = service.attach(ohlcv)
snap = service.snapshot(frame)
# snap.bullish / flipped_to_bullish / close_above / value

adapter = IndicatorAdapter(frame)
adapter.indicator("supertrend")           # after attach
adapter.indicator("supertrend_direction")
```

Canonical calc is also re-exported from `app.exit_engine.supertrend` for exit rules
(no duplicated algorithm).

---

## BUY

1. SuperTrend flips **Bearish → Bullish**  
2. Price closes **above** SuperTrend  
3. EMA trend bullish (`close > EMA50` and `EMA20 >= EMA50`)  
4. Relative volume > threshold  
5. Market structure bullish  

## SELL

1. SuperTrend flips **Bullish → Bearish**, **or**  
2. Price closes **below** SuperTrend  

## Filters (block longs)

Low volume · Sideways market · ATR below threshold · Weak structure  

---

## Risk

**Stop:** SuperTrend line → previous swing → ATR × 2  
**Targets:** RR 1:2 · ATR projection · nearest resistance  
**Holding:** Swing · 5–25 trading days  

## Confidence (100)

| Component | Weight |
|-----------|--------|
| Trend change | 30 |
| EMA confirmation | 20 |
| Market structure | 20 |
| Relative volume | 20 |
| ATR health | 10 |
