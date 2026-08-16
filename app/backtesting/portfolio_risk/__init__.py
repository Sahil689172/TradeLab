"""Portfolio-level risk and validation (Phase A5.8).

Overlays completed A5.2 trades onto a shared cash book. Does not rewrite
A5.1–A5.7 engines. Monte Carlo simulations resample historical evidence;
they do not create new independent historical observations.
"""

from app.backtesting.portfolio_risk.aggregation import portfolio_trades_from_sources
from app.backtesting.portfolio_risk.engine import PortfolioRiskEngine
from app.backtesting.portfolio_risk.exceptions import (
    PortfolioConfigError,
    PortfolioDataError,
    PortfolioRiskError,
)
from app.backtesting.portfolio_risk.export import write_outputs
from app.backtesting.portfolio_risk.report import format_markdown_report
from app.backtesting.portfolio_risk.schemas import (
    AllocationPolicy,
    LimitAction,
    PortfolioRejectReason,
    PortfolioRiskConfig,
    PortfolioRiskLimits,
    PortfolioRiskResult,
    PortfolioTrade,
)

__all__ = [
    "AllocationPolicy",
    "LimitAction",
    "PortfolioConfigError",
    "PortfolioDataError",
    "PortfolioRejectReason",
    "PortfolioRiskConfig",
    "PortfolioRiskEngine",
    "PortfolioRiskError",
    "PortfolioRiskLimits",
    "PortfolioRiskResult",
    "PortfolioTrade",
    "format_markdown_report",
    "portfolio_trades_from_sources",
    "write_outputs",
]
