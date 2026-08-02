"""Universe Strategy Validation — NIFTY500 execution contract checks."""

from app.services.universe_validation.aggregation import (
    aggregate_stock_stats,
    aggregate_strategy_stats,
)
from app.services.universe_validation.config import UniverseValidationConfig
from app.services.universe_validation.discovery import (
    discover_ohlcv_symbols,
    resolve_universe_symbols,
)
from app.services.universe_validation.engine import UniverseValidationEngine
from app.services.universe_validation.loaders import (
    load_symbol_features,
    synthetic_session_features,
)
from app.services.universe_validation.reports import (
    format_console_summary,
    write_csv_report,
    write_json_report,
    write_reports,
)
from app.services.universe_validation.schemas import (
    StockUniverseStats,
    StrategyUniverseStats,
    UniverseCellResult,
    UniverseValidationReport,
)

__all__ = [
    "StockUniverseStats",
    "StrategyUniverseStats",
    "UniverseCellResult",
    "UniverseValidationConfig",
    "UniverseValidationEngine",
    "UniverseValidationReport",
    "aggregate_stock_stats",
    "aggregate_strategy_stats",
    "discover_ohlcv_symbols",
    "format_console_summary",
    "load_symbol_features",
    "resolve_universe_symbols",
    "synthetic_session_features",
    "write_csv_report",
    "write_json_report",
    "write_reports",
]
