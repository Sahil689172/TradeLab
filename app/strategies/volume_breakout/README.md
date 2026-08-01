# Volume Breakout Strategy

**Module:** `app/strategies/volume_breakout/`  
**Strategy name:** `volume_breakout`  
**Volume service:** `app/services/strategy_engine/indicators/volume_analysis.py`

Volume-confirmed breaks of recent resistance / support. Volume math lives in
`VolumeAnalysisService` so ORB, CPR, VWAP, Confluence, and Strategy Builder can
reuse the same confirmation module.

---

## Reusable volume outputs

| Output | Description |
|--------|-------------|
| `volume_sma_20` / `volume_sma_5` | Period averages |
| `relative_volume_20` / `_5` | Volume ÷ average |
| `volume_spike` | RVOL ≥ spike multiple |
| `volume_expansion` / `volume_contraction` | Bar-over-bar change |
| `VolumeStatistics` | Snapshot for TradePlan / filters |

```python
from app.services.strategy_engine.indicators import VolumeAnalysisService

service = VolumeAnalysisService(spike_multiple=1.8)
frame = service.attach(ohlcv)
stats = service.snapshot(frame)
```

---

## BUY

Break above resistance **and** RVOL > 1.8 (configurable) **and** volume > 20-avg  
**and** bullish structure **and** close > VWAP **and** passes false-breakout filters.

## SELL

Break below support **and** RVOL **and** bearish structure **and** close < VWAP.

## False breakout filter

Rejects: breakout without volume · decreasing volume · weak candle body · late session.

---

## Risk

**Stop:** previous swing → ATR × 2 → VWAP  

**Targets:** TP1 = 1:2 RR · TP2 = nearest resistance/support or ATR projection  

**Holding:** intraday via Exit Engine  

---

## Usage

```python
from app.strategies.volume_breakout import (
    VolumeBreakoutConfig,
    register_volume_breakout_strategy,
)

register_volume_breakout_strategy(
    registry,
    VolumeBreakoutConfig(symbol="RELIANCE", relative_volume_threshold=1.8),
    market_structure=structure,
)
```

### Required columns

`date`, `open`, `high`, `low`, `close`, `volume`  

Optional: `atr_14`, precomputed VWAP / relative volume (service fills gaps).

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_volume_breakout.py
```
