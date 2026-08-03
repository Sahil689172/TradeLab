# Performance Profiling (Phase A4.15 / A4.16)

Measurement-only instrumentation for universe strategy validation.

**Does not optimize. Does not change strategy math or recommendation contracts.**

## Purpose

Identify where wall time is spent, then compare saved before/after profiles.

## Workflow (permanent optimization report)

```bat
REM 1. Baseline profile (save as before)
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 20 --workers 1 --label before

REM 2. Apply / keep optimizations in code

REM 3. After profile
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 20 --workers 1 --label after

REM 4. Compare existing reports only (does NOT re-run validation)
.venv\Scripts\python.exe backend\scripts\benchmark_optimization.py
```

## Progress

`profile_validation.py` prints live progress:

```
[5/100]  RELIANCE  elapsed 1m 12s  ETA 22m 40s
[25/100] ...
```

Disable with `--no-progress`.

## Layout

| File | Role |
|------|------|
| `timers.py` | Thread-safe `TimingCollector`, `ResourceMonitor` |
| `schemas.py` | `PerformanceProfileReport` |
| `profiler.py` | Instrumented runner |
| `progress.py` | `[n/total]` + ETA |
| `report.py` | Console / JSON / CSV profile writers |
| `compare.py` | Before/after optimization comparison |

## Outputs

| Artifact | Path |
|----------|------|
| Profile JSON | `backend/data/logs/performance_profile.json` |
| Labeled profile | `backend/data/logs/performance_profile_<label>.json` |
| Optimization report | `backend/data/logs/optimization_report.json` |
| Optimization text | `backend/data/logs/optimization_report.txt` |

## Comparison metrics

- Total Runtime (wall)
- Context Runtime
- Strategy Runtime
- Per Strategy Timing
- Peak Memory
- CPU Time
- Average Stock Runtime
- Average Strategy Runtime

Each metric shows **Before / After / Difference / Improvement %**.
