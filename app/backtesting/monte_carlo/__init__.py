"""Monte Carlo robustness layer (Phase A5.6).

Consumes completed A5.2 ``ClosedTradeRecord`` copies. Does not replay candles
inside the sampler and does not rewrite A5.1–A5.3.
"""

from app.backtesting.monte_carlo.adapter import trades_from_sources, with_cost_perturbation
from app.backtesting.monte_carlo.engine import MonteCarloEngine
from app.backtesting.monte_carlo.export import write_outputs
from app.backtesting.monte_carlo.pipeline import load_trades_from_json, load_trades_from_replay
from app.backtesting.monte_carlo.report import format_console_report, format_markdown_report
from app.backtesting.monte_carlo.schemas import (
    MonteCarloConfig,
    MonteCarloResult,
    MonteCarloTrade,
    RobustnessBand,
    SamplingMethod,
)
from app.backtesting.monte_carlo.simulation import simulate_equity

__all__ = [
    "MonteCarloConfig",
    "MonteCarloEngine",
    "MonteCarloResult",
    "MonteCarloTrade",
    "RobustnessBand",
    "SamplingMethod",
    "format_console_report",
    "format_markdown_report",
    "load_trades_from_json",
    "load_trades_from_replay",
    "simulate_equity",
    "trades_from_sources",
    "with_cost_perturbation",
    "write_outputs",
]
