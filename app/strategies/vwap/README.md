# VWAP Strategy

**Module:** `app/strategies/vwap/`  
**Strategy name:** `vwap`  
**VWAP service:** `app/services/strategy_engine/indicators/vwap.py`

Daily VWAP mean-reversion / continuation strategy with retest confirmation.
VWAP math is **not** inside the strategy — it lives in the shared `VWAPService`
so ORB, CPR, EMA, and Confluence can reuse it.

---

## Engines reused

| Concern | Module |
|---------|--------|
| Daily VWAP + slope | `VWAPService` (shared) |
| Retest / rejection | Condition Engine |
| Structure bias | Market Structure Engine |
| ATR read | Indicator Adapter (`vwap` / `atr` aliases) |
| RR target math | Risk Engine (`take_profit_from_risk`) |
| Nearest S/R target | Levels Engine snapshot |
| Session flatten | Exit Engine |
| Registry / runner | Strategy Foundation |

---

## VWAP modes (future-ready)

| Mode | Status |
|------|--------|
| Daily | Implemented |
| Weekly | Reserved (raises `VWAPNotImplementedError`) |
| Monthly | Reserved |
| Anchored | Reserved — do not implement yet |

```python
from app.services.strategy_engine.indicators import VWAPService, VWAPMode

service = VWAPService(mode=VWAPMode.DAILY, slope_lookback=3)
frame = service.attach(ohlcv)          # adds vwap, vwap_slope
snap = service.snapshot(frame)         # latest value / slope / side
```

Indicator Adapter aliases: `vwap`, `vwap_daily`, `vwap_slope`.

---

## BUY

Close > VWAP **and** slope > 0 **and** RVOL > 1.5 **and** structure bullish  
**and** successful VWAP retest (Condition Engine `retest ABOVE`).

## SELL

Close < VWAP **and** slope < 0 **and** RVOL > 1.5 **and** structure bearish  
**and** VWAP rejection (`retest BELOW`).

---

## Risk

**Stop priority:** VWAP → previous swing → ATR × 2  

**Targets:** TP1 = 1:2 RR · TP2 = nearest resistance (long) / support (short)  

**Holding:** intraday only — exit before market close  

---

## Confidence (/100)

| Component | Points |
|-----------|--------|
| VWAP position | 30 |
| Slope | 20 |
| Relative volume | 20 |
| Structure | 20 |
| Retest confirmation | 10 |

---

## Usage

```python
from app.strategies.vwap import VWAPStrategyConfig, register_vwap_strategy
from app.strategy_engine import StrategyRegistry, StrategyRunner

registry = StrategyRegistry()
strategy = register_vwap_strategy(
    registry,
    VWAPStrategyConfig(symbol="RELIANCE"),
    market_structure=structure,
    levels=levels_snapshot,  # optional — improves TP2
)
plan = StrategyRunner().run(features, strategy)
```

### Required columns

`date`, `open`, `high`, `low`, `close`, `relative_volume_20`  

Plus either precomputed `vwap` **or** raw `volume` (service computes Daily VWAP).

Optional: `atr_14` (ATR stop), Levels snapshot (TP2).

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_vwap_strategy.py
```
