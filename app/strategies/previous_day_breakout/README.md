# Previous Day High / Low (Magic Box) Strategy

**Module:** `app/strategies/previous_day_breakout/`  
**Strategy name:** `previous_day_breakout`

Multi-timeframe price-action breakout that uses **daily** Previous Day High / Low
levels and **15-minute** entries.

---

## Engines reused

| Concern | Module |
|---------|--------|
| PDH / PDL / S/R | Levels Engine |
| Trend bias | Market Structure Engine |
| Break / retest / touch | Condition Engine |
| ATR read | Indicator Adapter |
| Intraday time exit note | Exit Engine |
| Registry / runner | Strategy Foundation |

Indicators are **not** recalculated inside this strategy.

---

## Timeframes

1. **Daily** — `LevelsService.compute(daily_ohlcv)` → PDH / PDL (+ supports/resistances for TP2)
2. **15-minute** — entry sequencing against those levels (`features` DataFrame)

Bind daily context with `bind_daily(...)` or inject `bind_levels(...)`.

---

## BUY sequence

1. Approach PDH  
2. Break above PDH  
3. Retest PDH (from above)  
4. Bullish confirmation candle  
5. Relative volume `> 1.5`  
6. Market structure **bullish**  
7. → `BUY` TradePlan  

## SELL sequence

Mirror of the above against PDL with bearish structure.

---

## Risk

**Stop priority**

1. Previous candle low (long) / high (short)  
2. Previous Day Low / High  
3. ATR × 2  

**Targets**

- TP1 — Risk:Reward `1:2` (configurable)  
- TP2 — nearest resistance (long) or support (short) from Levels Engine  

**Holding**

- Intraday only (`session_bars`, default 25 × 15m)  
- Flatten before market close  

---

## Confidence scorecard (default / 100)

| Component | Points |
|-----------|--------|
| PDH/PDL break | 30 |
| Retest | 20 |
| Relative volume | 20 |
| Confirmation candle | 10 |
| Market structure | 20 |

Weights are configurable via `ConfidenceWeights`.

---

## Usage

```python
from app.strategies.previous_day_breakout import (
    PreviousDayBreakoutConfig,
    register_previous_day_breakout_strategy,
)
from app.strategy_engine import StrategyRegistry, StrategyRunner

registry = StrategyRegistry()
strategy = register_previous_day_breakout_strategy(
    registry,
    PreviousDayBreakoutConfig(symbol="RELIANCE"),
    daily_ohlcv=daily_df,           # or levels=levels_snapshot
    market_structure=structure,     # optional; else derived from 15m
)

plan = StrategyRunner().run(intraday_15m_features, strategy)
detailed = strategy.last_detailed_plan  # structure + levels_used + breakdown
```

### Required 15m columns

`date`, `open`, `high`, `low`, `close`, `relative_volume_20`  
Optional: `atr_14` (enables ATR stop fallback)

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_previous_day_breakout.py
```
