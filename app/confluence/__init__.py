"""Configurable multi-module confluence scoring."""

from app.confluence.engine import ConfluenceEngine
from app.confluence.exceptions import ConfluenceError, ConfluenceValidationError
from app.confluence.schemas import (
    ConfluenceConfig,
    ConfluenceModule,
    ConfluenceResult,
    ConfluenceVerdict,
    ModuleScore,
    ModuleWeights,
    SignalContribution,
    VerdictThresholds,
)

__all__ = [
    "ConfluenceConfig",
    "ConfluenceEngine",
    "ConfluenceError",
    "ConfluenceModule",
    "ConfluenceResult",
    "ConfluenceValidationError",
    "ConfluenceVerdict",
    "ModuleScore",
    "ModuleWeights",
    "SignalContribution",
    "VerdictThresholds",
]
