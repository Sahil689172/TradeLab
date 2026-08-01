# Central Pivot Range (CPR) Strategy

**Module:** `app/strategies/cpr/`  
**Strategy name:** `cpr`  
**Levels:** `LevelsSnapshot.cpr` via `app.levels.calculator.cpr_levels`

CPR geometry is owned by the **Levels Engine**. This strategy classifies the day
and generates TradePlans — it does not reimplement Pivot / BC / TC / R1–S3 math.

---

## Levels Engine (reusable)

```python
from app.levels import LevelsService, cpr_levels

snapshot = LevelsService().compute(ohlcv, symbol="RELIANCE")
cpr = snapshot.cpr  # pivot, bc, tc, lower, upper, width, width_pct
# Also: classic_pivot.R1–R3 / S1–S3, named PriceLevels CPR_PIVOT / CPR_BC / CPR_TC
```

Future ORB, PDH/PDL, Confluence, and Strategy Builder should read CPR from
`LevelsSnapshot` — never copy formulas.

---

## Classification (stored on TradePlan)

| Flag | Meaning |
|------|---------|
| Narrow CPR | `width_pct <= narrow_cpr_threshold` → **Trend** mode |
| Wide CPR | otherwise → **Reversal** mode |
| Inside / Outside | close vs `[lower, upper]` |
| Virgin CPR | session has not touched the CPR band |

---

## BUY / SELL

**Trend (Narrow):** breakout above TC / below BC + VWAP side + structure + RVOL  

**Reversal (Wide):** support bounce at BC / resistance reject at TC + VWAP + structure + RVOL  

VWAP from shared `VWAPService` (not recalculated here).

---

## Risk

**Stop:** nearest CPR level → swing → ATR × 2  

**Targets:** R1 / R2 / R3 (long) or S1 / S2 / S3 (short)  

**Holding:** intraday — Exit Engine time flatten  

---

## Usage

```python
from app.strategies.cpr import CPRStrategyConfig, register_cpr_strategy

strategy = register_cpr_strategy(
    registry,
    CPRStrategyConfig(symbol="RELIANCE"),
    market_structure=structure,
    levels=levels_snapshot,  # must include .cpr
)
```

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_cpr_strategy.py tests\test_levels.py
```
