# Professional EMA Trend Upgrade (Phase A4Y.1)

The EMA Trend strategy supports two modes without replacing the original behaviour.

## Modes

| Mode | Purpose |
|------|---------|
| `raw` (default) | Legacy EMA20/EMA50 true-cross + ADX + close-above-slow, ATR×2, EXIT on cross-below |
| `professional` | Institutional crossover system with modular filters and diagnostics |

## Professional defaults

```json
{
  "mode": "professional",
  "fast_ema": 9,
  "slow_ema": 21,
  "confirm_on_close": true,
  "trend_filter": true,
  "ema200_filter": true,
  "adx_filter": true,
  "adx_threshold": 25,
  "volume_filter": true,
  "relative_volume": 1.2,
  "atr_stop": true,
  "atr_multiplier": 1.5,
  "atr_trailing": false
}
```

EMA pair presets: `9_21`, `12_26`, `20_50`, `50_200`.

## Signal rules (professional)

1. **True crossover only** — BUY when yesterday fast≤slow and today fast>slow; SELL when the opposite cross fires.
2. **No duplicate BUY/SELL** while the same side remains active.
3. **Confirm on close** (default) — intrabar crosses are rejected.
4. **EMA200 / ADX / Volume** gates with recorded rejection diagnostics.
5. **ATR stop** = entry ± `atr_multiplier × ATR`; optional ATR trailing.

## Factory

```python
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy

raw = EMATrendStrategy(EMATrendConfig(symbol="RELIANCE"))  # mode=raw
pro = EMATrendStrategy(EMATrendConfig.professional(symbol="RELIANCE"))
```

Example config: `backend/data/configs/ema_trend.professional.example.json`.

## Audit funnel

Professional evaluations accumulate:

Raw BUY/SELL → Rejected by EMA200 / ADX / Volume / ATR / Other → Final BUY/SELL  
plus acceptance and rejection rates.

## Scripts

- `backend/scripts/compare_ema_modes.py` — RAW vs PROFESSIONAL comparison
- `backend/scripts/validate_ema_professional.py` — universe validation
- `backend/scripts/audit_strategies.py` — general strategy audit
