# Walk-forward / out-of-sample validation (A5.9)

Walk-forward validation asks whether a strategy’s **in-sample** performance
survives on data that was **not** used to choose its configuration.

It does **not** prove future profitability. A strong walk-forward result is
still a historical statement about this sample, these costs, and this search
space.

## Train vs test

Each window has two adjacent periods:

| Segment | Bound | Allowed use |
|---------|--------|-------------|
| TRAIN | `[train_start, train_end]` | Parameter/configuration selection only |
| TEST (OOS) | `[test_start, test_end]` | Frozen evaluation only |

All optimization, threshold selection, trade filtering, and sizing knobs that
A5.9 searches must use `timestamp <= train_end`. The chosen configuration is
**frozen**. Only then does the test period run.

Training trades are **never** mixed into combined OOS performance.

## Rolling windows

Default calendar specification (not hardcoded in callers):

- `--train-years 5`
- `--test-years 1`
- `--step-years 1`

Example:

```text
Train 2016-01-01 → 2020-12-31    Test 2021
Train 2017-01-01 → 2021-12-31    Test 2022
Train 2018-01-01 → 2022-12-31    Test 2023
```

`--train-days` / `--test-days` / `--step-days` select day-length windows instead.
`--embargo-days` inserts a gap after `train_end` before `test_start`.

Windows stop when the next test period would extend past available data.

## Indicator warmup vs leakage

Replay already keeps **pre-start** candles for indicator history (A5.1). A5.9
adds a hard **period-end cap**:

- Training may see candles with `date <= train_end` (including pre-train warmup).
- Testing may see candles with `date <= test_end` (including pre-test warmup).
- Neither side may see candles **after** its period end.

Example: a 2023 test that needs EMA200 may use 2022 candles. It must not use
2024 candles.

Computing EMA200 from **only** 2023-01-01 onward is a different error
(insufficient warmup), not a license to read the future.

## Parameter selection

A5.9 is not a general optimizer. It searches a **declared** grid only.

Default EMA grid (three candidates unless you widen it):

- pair presets: `9_21`, `12_26`, `20_50`
- ADX: `20`
- EMA200 filter: enabled (`--ema200 on`)

`--ema200 both` also searches EMA200 disabled and **doubles** runtime. `--fast` /
`--slow` / `--adx` expand the grid. Combinations above `--max-candidates`
(default 24) are rejected rather than silently exploded.

Training walks each window **once** with every declared candidate in the same
A5.1 replay, then scores each candidate with a separate A5.2 broker. Out-of-sample
still uses the frozen configuration only.

Selection score (deterministic):

`Sharpe + 0.5 × return − max drawdown + small trade-count tie-break`

Ties break on `config_key` lexicographic order.

`--selection-scope per_symbol` (default) fits each symbol on that symbol’s
training data only. `joint` scores one configuration across every symbol’s
**training** windows; test data still stays unused.

## OOS evaluation

The frozen configuration is replayed through A5.1 and filled by A5.2 (same
brokerage, slippage, whole-share, and cash rules as the rest of TradeLab).
OOS records include trades, P&L, costs, rejected orders, and the window equity
path.

## Combined OOS equity

Test windows are concatenated in time. Training equity is omitted.

`--capital-mode compounded` (default): the next test window starts at the
previous test window’s ending equity.

`--capital-mode fixed`: every test window restarts at `--initial-capital`.

## Train vs OOS degradation

Reported ratios are **OOS / Train**. Degradation percent is
`(Train − OOS) / |Train|`.

Caution bands (`degradation_return_caution`, `degradation_sharpe_caution`,
default 0.5) are diagnostics. Crossing a band is **not** an automatic fail.

## Parameter stability

A5.9 records the selected `config_key` per window: frequency, number of
changes, most frequent configuration, and
`stability_score = 1 − changes / (windows − 1)`.

Fragile parameter hopping is a diagnostic, not a profitability claim.

## Regime awareness

A5.9 reports OOS contribution by **calendar year** and **symbol**. It does not
add a new regime classifier. Existing volatility-regime filters remain inside
the strategy filter pipeline.

## Monte Carlo relationship

If `--monte-carlo` is set:

```text
TRAIN → freeze → OOS TEST → collect OOS trades → after all windows
    → Monte Carlo on the OOS trade history only
```

This is labeled **OUT-OF-SAMPLE MONTE CARLO**. Simulations resample observed
OOS trades; they do not create new independent historical observations.

If the OOS trade count is ≤ 4, the verdict is `INSUFFICIENT_EVIDENCE` even when
the simulated distribution looks favorable.

Optional `--portfolio-risk` runs A5.8 on the same OOS trades. A5.8 is not
rebuilt.

## Leakage controls

- Date-capped market/feature adapters (`date <= period_end`)
- Train/test windows: `train_end < test_start`, no shared timestamps
- Adversarial test: mutating prices after `train_end` must not change the
  selected training configuration
- Parquet is loaded **once per symbol** (cached) so candidate search does not
  re-read files

## Architecture

```text
Market Data (cached)
    → Walk-Forward Controller
        → Training evaluator / declared grid (train cap)
        → Frozen strategy configuration
        → A5.1 Replay + A5.2 Execution (test cap, pre-test warmup)
        → A5.3 is not required for this layer
        → Combined OOS trades / equity
        → optional A5.8 Portfolio Risk
        → optional A5.6 OUT-OF-SAMPLE Monte Carlo
```

A5.9 does not replace A5.1–A5.8.

## Limitations

- The search space is small and EMA-centric in this version.
- Warmup uses pre-period history; results still depend on that history being
  available and causal.
- Combined OOS is a stitched historical path, not a live portfolio.
- Small OOS trade counts cannot support a `ROBUST` claim.
- Walk-forward cannot certify that the same configuration will work tomorrow.

## CLI (Windows CMD)

From the repository root:

```bat
.venv\Scripts\python.exe backend\scripts\walk_forward.py --symbol RELIANCE --train-years 5 --test-years 1 --step-years 1 --initial-capital 100000 --strategy ema_professional --seed 42 --no-monte-carlo --output backend\data\walk_forward\reliance

.venv\Scripts\python.exe backend\scripts\walk_forward.py --symbol RELIANCE --train-years 5 --test-years 1 --step-years 1 --initial-capital 500 --strategy ema_professional --seed 42 --no-monte-carlo --output backend\data\walk_forward\reliance_500

.venv\Scripts\python.exe backend\scripts\walk_forward.py --symbols RELIANCE,TCS --train-years 5 --test-years 1 --step-years 1 --monte-carlo --simulations 1000 --seed 42 --output backend\data\walk_forward\multi
```

Outputs under the `--output` directory:

- `walk_forward_report.json` / `.md`
- `windows.csv`, `train_metrics.csv`, `oos_metrics.csv`
- `oos_trades.csv`, `parameter_history.csv`, `equity_curve.csv`
- `leakage_report.json`
- optional PNG charts when matplotlib is installed
