"""Monte Carlo robustness layer (Phase A5.6).

Consumes completed A5.2 ``ClosedTradeRecord`` copies. Does not replay candles
inside the sampler and does not rewrite A5.1–A5.3.

Monte Carlo simulations resample historical evidence; they do not create new
independent historical observations.
"""

from app.backtesting.monte_carlo.adapter import (
    reconstruct_net_pnl,
    trades_from_sources,
    with_cost_perturbation,
)
from app.backtesting.monte_carlo.engine import MonteCarloEngine, TradeResamplingMonteCarlo
from app.backtesting.monte_carlo.exceptions import (
    MonteCarloConfigError,
    MonteCarloDataError,
    PathDependentNotImplementedError,
)
from app.backtesting.monte_carlo.export import write_outputs
from app.backtesting.monte_carlo.path_dependent import (
    PathDependentMonteCarlo,
    PathDependentPortfolioMonteCarlo,
)
from app.backtesting.monte_carlo.pipeline import (
    load_trades_from_json,
    load_trades_from_replay,
    make_synthetic_trades,
)
from app.backtesting.monte_carlo.report import format_console_report, format_markdown_report
from app.backtesting.monte_carlo.schemas import (
    CapitalMode,
    EngineMode,
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloTrade,
    MonteCarloVerdict,
    MonteCarloSizingMode,
    RobustnessBand,
    SampleQuality,
    SamplingMethod,
)
from app.backtesting.monte_carlo.simulation import simulate_equity

__all__ = [
    "CapitalMode",
    "EngineMode",
    "MonteCarloConfig",
    "MonteCarloConfigError",
    "MonteCarloDataError",
    "MonteCarloEngine",
    "MonteCarloResult",
    "MonteCarloTrade",
    "MonteCarloSizingMode",
    "MonteCarloVerdict",
    "PathDependentMonteCarlo",
    "PathDependentPortfolioMonteCarlo",
    "PathDependentNotImplementedError",
    "RobustnessBand",
    "SampleQuality",
    "SamplingMethod",
    "TradeResamplingMonteCarlo",
    "format_console_report",
    "format_markdown_report",
    "load_trades_from_json",
    "load_trades_from_replay",
    "make_synthetic_trades",
    "reconstruct_net_pnl",
    "simulate_equity",
    "trades_from_sources",
    "with_cost_perturbation",
    "write_outputs",
]
