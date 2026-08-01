# Break & Retest Strategy

**Module:** `app/strategies/break_retest/`  
**Strategy name:** `break_retest`  
**Detection engine:** `app/services/strategy_engine/break_retest/`

Reusable break → retest → confirmation sequence. Strategies should inject
`BreakRetestEngine` rather than reimplementing detection.

---

## Reusable components

```python
from app.services.strategy_engine.break_retest import (
    BreakRetestEngine,
    detect_break,
    detect_retest,
    detect_confirmation_candle,
)

engine = BreakRetestEngine()
long_seq, short_seq = engine.scan_both(ohlcv, resistance=100.0, support=90.0)
# stages: NONE | BROKEN | RETESTED | FAILED_RETEST | CONFIRMED
```

Detects: **Break** · **Retest** · **Confirmation Candle** · Failed retest · False breakout.

---

## BUY

1. Resistance broken  
2. Successful retest  
3. Bullish confirmation candle  
4. Relative volume healthy  
5. Market structure bullish  

## SELL

1. Support broken  
2. Retest  
3. Bearish confirmation  

---

## Risk

**Stop:** Retest Low (long) / Retest High (short) → ATR  
**Targets:** RR 1:2 · ATR projection  

**TradePlan:** Entry · Stop · Targets · Confidence · Reasons
