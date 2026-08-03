# Performance Profiling (Phase A4.15)

Measurement-only instrumentation for universe strategy validation.

**Does not optimize. Does not change strategy math or recommendation contracts.**

## Purpose

Identify where wall time is spent across:

1. Universe discovery  
2. Parquet loading (OHLCV + features)  
3. Strategy context creation (daily / VWAP / CPR / session / ranking / structure)  
4. Per-strategy execution  
5. Trade recommendation construction + validation  
6. Report generation (JSON / CSV / console)  
7. Overall wall / CPU / memory  

## Layout

| File | Role |
|------|------|
| `timers.py` | Thread-safe `TimingCollector`, `ResourceMonitor` |
| `schemas.py` | `PerformanceProfileReport` and related models |
| `profiler.py` | Instrumented runner wrapping existing validation path |
| `report.py` | Console / JSON / CSV writers |

## CLI

From the project root:

```bat
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 20 --workers 1
.venv\Scripts\python.exe backend\scripts\profile_validation.py --symbol RELIANCE --workers 1
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 100 --workers 4
```

### Flags

| Flag | Meaning |
|------|---------|
| `--limit N` | Cap symbols after discovery |
| `--symbol` | Repeatable symbol filter (or omit for all) |
| `--workers N` | Parallel per-symbol workers (default 1 for clearer additive timings) |
| `--strategy` | Repeatable strategy alias or `all` |
| `--allow-synthetic` | Synthetic features when parquet missing (tests/dev) |
| `--output-dir` | Report directory (default: settings log dir) |
| `--storage-dir` | OHLCV parquet directory |

## Outputs

| Artifact | Path |
|----------|------|
| Console | stdout |
| JSON | `backend/data/logs/performance_profile.json` |
| CSV | `backend/data/logs/performance_profile.csv` |

## Interpreting the report

- **Hotspots** — top contributors (parquet load, context, individual strategies, recommendations). Focus optimization here next.  
- **Per strategy** — avg / min / max / total across symbols.  
- **Per stock** — load + context + each strategy + recommendation.  
- **Runtime estimates** — linear extrapolation from average stock runtime to 100 / 449 / 1000 stocks.  
- With `--workers > 1`, summed section times can exceed wall clock (parallel overlap). Prefer `--workers 1` when comparing additive section shares.

## Design notes

- Context subtype timings come from `ProfilingContextProvider` (same assemble steps as production).  
- Strategy execution uses `execute_context` after a timed `prepare`.  
- Recommendation construction vs validation are timed separately.  
- Aggregation is recorded as a zero-cost placeholder (unused on the per-cell validation path).
