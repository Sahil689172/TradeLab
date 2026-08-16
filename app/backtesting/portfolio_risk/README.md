# Portfolio-level risk (A5.8)

Post-trade overlay of **completed** A5.2 trades onto a **shared cash book**.

This package does not rewrite A5.1 replay, A5.2 execution math, A5.3 position
management, A5.6 trade-resampling Monte Carlo, or A5.7 sequential
path-dependent Monte Carlo.

**Monte Carlo simulations resample historical evidence; they do not create new
independent historical observations.**

Independent per-symbol backtest quantities are **not** treated as a live
portfolio. Each entry is re-sized from current cash using the allocation
policy and A5.2 `quantity_from_budget` / `SimulatedBroker`.
