"""Walk-forward / out-of-sample validation (Phase A5.9 / A5.10).

Orchestrates TRAIN → freeze → TEST → roll using A5.1 replay and A5.2 execution.
Does not rewrite A5.1–A5.8. Combined OOS concatenates test-period trades only.

Walk-forward does not prove future profitability.
"""

from app.backtesting.walk_forward.engine import WalkForwardEngine
from app.backtesting.walk_forward.exceptions import (
    WalkForwardConfigError,
    WalkForwardError,
    WalkForwardLeakageError,
)
from app.backtesting.walk_forward.export import write_outputs
from app.backtesting.walk_forward.isolation import DateCappedFeatures, DateCappedMarket, cap_frame
from app.backtesting.walk_forward.report import format_markdown_report
from app.backtesting.walk_forward.schemas import (
    AllocationModel,
    CapitalMode,
    SearchSpace,
    SelectionScope,
    WalkForwardConfig,
    WalkForwardResult,
)
from app.backtesting.walk_forward.windows import generate_windows

__all__ = [
    "AllocationModel",
    "CapitalMode",
    "DateCappedFeatures",
    "DateCappedMarket",
    "SearchSpace",
    "SelectionScope",
    "WalkForwardConfig",
    "WalkForwardConfigError",
    "WalkForwardEngine",
    "WalkForwardError",
    "WalkForwardLeakageError",
    "WalkForwardResult",
    "cap_frame",
    "format_markdown_report",
    "generate_windows",
    "write_outputs",
]
