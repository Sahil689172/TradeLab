"""
Absolutely minimal test - NO app imports at all.
Copies the two functions inline and tests them directly.
Run: .venv\Scripts\python.exe scripts\run_mc_minimal.py
"""
import sys, time
from pathlib import Path

OUT = Path(__file__).parent / "mc_minimal_output.txt"
lines = []
def log(m=""): lines.append(str(m)); print(m, flush=True)

log("Starting - numpy import...")
t0 = time.perf_counter()
import numpy as np
log(f"numpy OK in {(time.perf_counter()-t0)*1000:.0f}ms")

passed = failed = 0
def run(name, fn):
    global passed, failed
    try:
        t0 = time.perf_counter()
        fn()
        log(f"  PASS  {name}  ({(time.perf_counter()-t0)*1000:.1f}ms)")
        passed += 1
    except Exception as e:
        log(f"  FAIL  {name}  => {type(e).__name__}: {e}")
        failed += 1

# ── INLINE copies of both implementations ──────────────────────────────────

def _max_run_old(mask):
    """Original Python loop."""
    n_sims, n_steps = mask.shape
    runs = np.zeros(n_sims, dtype=np.int32)
    best = np.zeros(n_sims, dtype=np.int32)
    for t in range(n_steps):
        runs = np.where(mask[:, t], runs + 1, 0)
        best = np.maximum(best, runs)
    return best

def _max_run_new(mask):
    """New vectorised implementation."""
    n_sims, n_steps = mask.shape
    if n_steps == 0:
        return np.zeros(n_sims, dtype=np.int32)
    m = mask.astype(np.int8)
    padded = np.pad(m, ((0,0),(1,1)), constant_values=0)
    d = np.diff(padded.astype(np.int16), axis=1)
    best = np.zeros(n_sims, dtype=np.int32)
    starts = np.full(n_sims, -1, dtype=np.int32)
    for col in range(d.shape[1]):
        col_d = d[:, col]
        started = col_d == 1
        starts = np.where(started, col, starts)
        ended = col_d == -1
        length = np.where(ended & (starts >= 0), col - starts, 0).astype(np.int32)
        best = np.maximum(best, length)
    return best

log("\n== _max_run CORRECTNESS ==")
run("all_true",    lambda: np.testing.assert_array_equal(_max_run_new(np.ones((4,6),bool)), [6,6,6,6]))
run("all_false",   lambda: np.testing.assert_array_equal(_max_run_new(np.zeros((4,6),bool)), [0,0,0,0]))
run("alternating", lambda: np.testing.assert_array_equal(_max_run_new(np.array([[True,False,True,False,True,False]])), [1]))
run("run_at_end",  lambda: np.testing.assert_array_equal(_max_run_new(np.array([[False,False,True,True,True]])), [3]))
run("run_at_start",lambda: np.testing.assert_array_equal(_max_run_new(np.array([[True,True,False,False,False]])), [2]))
run("empty_steps", lambda: np.testing.assert_array_equal(_max_run_new(np.zeros((5,0),bool)), [0,0,0,0,0]))
run("single_step", lambda: np.testing.assert_array_equal(_max_run_new(np.array([[True],[False],[True]])), [1,0,1]))

def t_multi():
    m = np.array([[True,True,False,True],[False,False,False,False],[True,True,True,True],[False,True,False,True]], dtype=bool)
    np.testing.assert_array_equal(_max_run_new(m), [2,0,4,1])
    np.testing.assert_array_equal(_max_run_new(m), _max_run_old(m))
run("multi_row", t_multi)

log("\n== MATCH REFERENCE (random) ==")
for ns, nt in [(1,1),(10,20),(100,50),(1000,100),(5000,200)]:
    def mk(ns,nt):
        def fn():
            mask = np.random.default_rng(42).random((ns,nt)) > 0.5
            np.testing.assert_array_equal(_max_run_new(mask), _max_run_old(mask))
        return fn
    run(f"n_sims={ns},n_steps={nt}", mk(ns,nt))

log("\n== SPEEDUP (new vs old) ==")
timings = {}
for ns, nt in [(1000,50),(10000,50),(100000,50),(1000,200)]:
    mask = np.random.default_rng(7).random((ns,nt)) > 0.5
    t0=time.perf_counter(); _max_run_old(mask); t_ref=time.perf_counter()-t0
    t0=time.perf_counter(); _max_run_new(mask); t_new=time.perf_counter()-t0
    sp = t_ref/t_new if t_new>0 else float("inf")
    timings[(ns,nt)] = (t_ref, t_new, sp)
    log(f"  n_sims={ns:>6}  n_steps={nt:>3}  OLD={t_ref*1000:7.2f}ms  NEW={t_new*1000:7.2f}ms  speedup={sp:.1f}x")

log("\n== RESULT ==")
log(f"  Passed: {passed}  Failed: {failed}")
log("\nSPEEDUP TABLE:")
log(f"  {'Shape':>20}  {'OLD(ms)':>10}  {'NEW(ms)':>10}  {'Speedup':>8}")
for (ns,nt),(tr,tn,sp) in timings.items():
    log(f"  ({ns:>6},{nt:>3})       {tr*1000:>10.2f}  {tn*1000:>10.2f}  {sp:>7.1f}x")

OUT.write_text("\n".join(lines), encoding="utf-8")
log(f"\nWritten to {OUT}")
sys.exit(0 if failed==0 else 1)
