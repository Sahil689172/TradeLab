# Market Structure Engine

**Module:** `app/market_structure/`  
**Status:** Foundation (no strategies)  
**Version:** 1.0.0

---

## Purpose

The Market Structure Engine converts raw OHLCV bars into deterministic, reusable
structure objects that strategies can consume later:

- Swing High / Swing Low
- Higher High / Higher Low / Lower High / Lower Low
- Trend: Bullish / Bearish / Sideways
- Break of Structure (BOS)
- Change of Character (ChoCH)

It uses **price structure only**. No EMA, RSI, ATR, volume indicators, or other
derived indicators are involved.

---

## Package layout

```
app/market_structure/
  __init__.py          Public exports
  schemas.py           Pydantic models
  detector.py          Pure detection functions
  service.py           MarketStructureService facade
  exceptions.py        Typed errors
```

---

## Public API

```python
from app.market_structure import MarketStructureService, TrendDirection

service = MarketStructureService(swing_length=2)
result = service.analyze(ohlcv_df, symbol="RELIANCE")

result.trend          # BULLISH | BEARISH | SIDEWAYS
result.swings         # list[SwingPoint]
result.events         # list[StructureEvent]  (BOS / ChoCH)
result.last_swing_high
result.last_swing_low
```

### Input requirements

| Column | Required | Notes |
|--------|----------|--------|
| `date` | yes | Converted to datetime, sorted ascending, deduplicated |
| `open` | yes | Numeric |
| `high` | yes | Must be >= open, close, low |
| `low` | yes | Must be <= open, close, high |
| `close` | yes | Used for BOS/ChoCH confirmation |
| `volume` | yes | Present for OHLCV contract; unused by detection rules |

Minimum bars: `swing_length * 2 + 1`.

---

## Detection rules (deterministic)

### 1. Swing High / Swing Low

With lookback `L = swing_length`:

- Bar `i` is a **Swing High** iff  
  `high[i] > max(high[i-L : i])` and `high[i] > max(high[i+1 : i+L+1])`
- Bar `i` is a **Swing Low** iff  
  `low[i] < min(low[i-L : i])` and `low[i] < min(low[i+1 : i+L+1])`

A swing at index `i` is **confirmed** at index `i + L`.

Comparisons are **strict**, so plateaus do not create ambiguous pivots.

### 2. Alternation

Consecutive same-type swings are collapsed to one extreme:

- Consecutive highs → keep the higher price (earlier bar on ties)
- Consecutive lows → keep the lower price (earlier bar on ties)

This yields an alternating high/low sequence suitable for structure labeling.

### 3. Structure labels

Each swing is labeled against the previous swing of the **same type**:

| Condition | Label |
|-----------|--------|
| Swing high > prior swing high | `HIGHER_HIGH` |
| Swing high < prior swing high | `LOWER_HIGH` |
| Swing high == prior swing high | `EQUAL_HIGH` |
| Swing low > prior swing low | `HIGHER_LOW` |
| Swing low < prior swing low | `LOWER_LOW` |
| Swing low == prior swing low | `EQUAL_LOW` |

The first swing of each type has `structure_label = null`.

### 4. Trend

Using the most recent labeled swing high **and** swing low:

| Last high | Last low | Trend |
|-----------|----------|--------|
| `HIGHER_HIGH` | `HIGHER_LOW` | `BULLISH` |
| `LOWER_HIGH` | `LOWER_LOW` | `BEARISH` |
| anything else / insufficient history | | `SIDEWAYS` |

### 5. Break of Structure (BOS) and Change of Character (ChoCH)

Events are evaluated only on bars **after** a swing’s confirmation index.
Confirmation uses the bar **close** strictly beyond the active swing level:

| Prevailing trend | Close > last swing high | Close < last swing low |
|------------------|-------------------------|------------------------|
| `BULLISH` | Bullish **BOS** | Bearish **ChoCH** |
| `BEARISH` | Bullish **ChoCH** | Bearish **BOS** |
| `SIDEWAYS` | Bullish **BOS** | Bearish **BOS** |

Each swing level emits at most one break event.

---

## Output contracts

### `SwingPoint`

- `index`, `timestamp`, `price`
- `swing_type`: `SWING_HIGH` | `SWING_LOW`
- `structure_label`: HH/HL/LH/LL/equal or `null`
- `confirmation_index`

### `StructureEvent`

- `event_type`: `BREAK_OF_STRUCTURE` | `CHANGE_OF_CHARACTER`
- `direction`: `BULLISH` | `BEARISH`
- `broken_level`, `reference_swing_index`, `confirmation_price`

### `MarketStructureResult`

Immutable snapshot containing trend, swings, events, and last swing high/low.
Safe to pass into future strategy layers without recomputation.

---

## Design constraints

- OHLCV only — no indicator imports or calculations
- Deterministic — same input + `swing_length` ⇒ identical result
- No strategy, risk, or order logic
- Strict typing via Pydantic (`frozen=True`, `extra="forbid"`)

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q tests\test_market_structure.py
```

Coverage includes swing detection, HH/HL/LH/LL labels, trend classification,
bullish BOS, bearish ChoCH, validation errors, and determinism.

---

## Extension points (later)

- Strategy adapters that map `MarketStructureResult` into `Signal` / `TradePlan`
- Optional multi-timeframe aggregation
- Persistence of structure snapshots beside feature Parquet files

Do not embed those concerns in this module until explicitly required.
