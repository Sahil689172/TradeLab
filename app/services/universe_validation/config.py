"""Configuration for NIFTY500 / universe strategy validation."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class UniverseValidationConfig(BaseModel):
    """Tunable knobs for universe-wide strategy validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_dir: Path | None = None
    output_dir: Path | None = None
    timeframe: str = "15 Minute"
    workers: int = Field(default=4, ge=1, le=64)
    limit: int | None = Field(default=None, ge=1)
    allow_synthetic: bool = False
    json_filename: str = "universe_validation.json"
    csv_filename: str = "universe_validation.csv"
