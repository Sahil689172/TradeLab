# Opening Range Breakout (ORB) Strategy

**Module:** `app/strategies/opening_range_breakout/`  
**Strategy name:** `opening_range_breakout`

Intraday breakout of a configurable opening range (5 / 15 / 30 minutes).

---

## Engines reused

| Concern | Module |
|---------|--------|
| Opening Range High / Low | Levels Engine (`opening_range`) |
| Structure bias | Market Structure Engine |
| Close vs ORH/ORL | Condition Engine |
| ATR / EMA reads | Indicator Adapter |
| RR target math | Risk Engine (`take_profit_from_risk`) |
| Trend reinforcement | Confluence Engine |
| Session flatten | Exit Engine |
| Registry / runner | Strategy Foundation |

---

## Opening range (not hardcoded)

```python
OpeningRangeBreakoutConfig(
    opening_range_minutes=15,  # 5 | 15 | 30
    bar_minutes=5,             # must divide OR minutes evenly
)
# opening_range_bars = opening_range_minutes // bar_minutes
```

ORM = (ORH + ORL) / 2.

---

## BUY

Close > ORH **and** RVOL > 1.5 **and** structure bullish **and** trend bullish **and** no prior breakout today.

## SELL

Close < ORL **and** RVOL > 1.5 **and** structure bearish **and** no prior breakout today.

## Filters

- Low volume  
- Range too small / too large  
- Late breakout  
- News gap over configured %  

---

## Risk

**Stop priority:** Opening Range → previous swing → ATR × 2  

**Targets:** TP1 = 1:2 RR · TP2 = ATR projection  

**Holding:** intraday only — exit before market close  

---

## Confidence (/100)

| Component | Points |
|-----------|--------|
| OR break | 30 |
| Volume | 20 |
| Trend | 20 |
| Structure | 20 |
| Momentum | 10 |

---

## Usage

```python
from app.strategies.opening_range_breakout import (
    OpeningRangeBreakoutConfig,
    register_opening_range_breakout_strategy,
)
from app.strategy_engine import StrategyRegistry, StrategyRunner

registry = StrategyRegistry()
strategy = register_opening_range_breakout_strategy(
    registry,
    OpeningRangeBreakoutConfig(symbol="RELIANCE", opening_range_minutes=15, bar_minutes=5),
    market_structure=structure,  # optional
)
plan = StrategyRunner().run(intraday_features, strategy)
detailed = strategy.last_detailed_plan
```

### Required columns

`date`, `open`, `high`, `low`, `close`, `relative_volume_20`  

Optional: `atr_14`, `ema_20`, `ema_50` (ATR stop/target + trend filter)

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_opening_range_breakout.py
```
