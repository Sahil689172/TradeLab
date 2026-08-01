# Donchian Channel (Turtle Trading) Strategy

**Module:** `app/strategies/donchian/`  
**Strategy name:** `donchian`  
**Channel service:** `app/services/strategy_engine/indicators/donchian.py`

Standalone Turtle-style breakout strategy backed by a **reusable Donchian
Channel service**. Future breakout strategies and Confluence should inject
`DonchianChannelService` rather than reimplementing channel math.

Defaults: **entry lookback = 20**, **exit lookback = 10** (configurable for
55-period Turtle entry).

---

## Reusable channel

```python
from app.services.strategy_engine.indicators import DonchianChannelService
from app.indicator_adapter import IndicatorAdapter

service = DonchianChannelService(entry_lookback=20, exit_lookback=10)
frame = service.attach(ohlcv)
snap = service.snapshot(frame)
# snap.upper / middle / lower
# snap.entry_upper / entry_lower  (prior N — breakout levels)
# snap.breakout_above / breakout_below / false_breakout_above

adapter = IndicatorAdapter(frame)
adapter.indicator("donchian_upper")
adapter.indicator("donchian_middle")
adapter.indicator("donchian_lower")
```

---

## BUY

1. Close above upper Donchian (entry channel)  
2. EMA trend bullish  
3. Relative volume healthy  
4. Market structure bullish  
5. No recent breakout within cooldown  

## SELL

Close below lower Donchian (entry channel)

## Exits

Close below exit channel **or** ATR trailing stop **or** trend turns bearish

## Filters

Low ATR · Weak volume · Sideways · False breakout (wick)

---

## Risk

**Stop:** Middle channel → ATR × 2 → previous swing  
**Targets:** Open trend-following · fixed RR · trailing Donchian / ATR exit  
**Holding:** Swing / positional · 10–60 trading days  

## Confidence (100)

| Component | Weight |
|-----------|--------|
| Channel breakout | 30 |
| Trend | 20 |
| Volume | 20 |
| Market structure | 20 |
| ATR | 10 |
