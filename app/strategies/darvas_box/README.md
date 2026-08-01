# Darvas Box Strategy

**Module:** `app/strategies/darvas_box/`  
**Strategy name:** `darvas_box`  
**Box engine:** `app/services/strategy_engine/darvas/`

Classic Nicolas Darvas box breakout. Box detection is a **reusable engine** —
future strategies should inject `DarvasBoxEngine`, not copy detection logic.

---

## Reusable detection

```python
from app.services.strategy_engine.darvas import DarvasBoxEngine, DarvasBoxState

engine = DarvasBoxEngine()
snap = engine.detect(ohlcv)
# snap.state: FORMING | CONSOLIDATION | BREAKOUT | BREAKDOWN | NEW_BOX
# snap.box.upper / snap.box.lower
```

Detects: Upper Box · Lower Box · Consolidation · Breakout · New Box Formation.

---

## BUY

Close above Upper Box **and** volume expansion **and** EMA trend bullish.

## SELL

Close below Lower Box.

## Risk

**Stop:** Lower Box → ATR × 2  
**Targets:** RR 1:2 · ATR projection  

---

## TradePlan

Current Box · Entry · Stop · Targets · Confidence · Reasons

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_darvas_box.py
```
