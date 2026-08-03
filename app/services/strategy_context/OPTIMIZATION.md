# Strategy Context Performance (Phase A4.16)

Architectural optimizations for universe validation. **Strategy math and
TradeRecommendation contracts are unchanged.**

## Measuring impact (do not double-run validation)

```bat
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 20 --workers 1 --label before
REM ... keep / apply optimizations ...
.venv\Scripts\python.exe backend\scripts\profile_validation.py --limit 20 --workers 1 --label after
.venv\Scripts\python.exe backend\scripts\benchmark_optimization.py
```

`benchmark_optimization.py` only compares saved JSON profiles.

## What changed

1. **`ContextRunCache`** — thread-safe, run-scoped cache  
2. **Lazy + cached prepare** — artifacts built at most once per key  
3. **Shared cache across workers**  
4. **Market structure** — vectorized swings  
5. **Break & Retest / SuperTrend** — NumPy paths + assess reuse  
