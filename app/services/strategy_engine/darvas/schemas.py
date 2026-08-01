"""Reusable Darvas Box detection schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DarvasBoxState(str, Enum):
    """Lifecycle state of the current Darvas box."""

    FORMING = "FORMING"
    CONSOLIDATION = "CONSOLIDATION"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    NEW_BOX = "NEW_BOX"


class DarvasBox(BaseModel):
    """A single Darvas box (upper / lower bounds + provenance)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    upper: float = Field(..., gt=0.0, description="Upper box (box top)")
    lower: float = Field(..., gt=0.0, description="Lower box (box bottom)")
    top_index: int = Field(..., ge=0)
    bottom_index: int = Field(..., ge=0)
    formed_index: int = Field(..., ge=0, description="Bar index when box became active")
    top_time: datetime | None = None
    bottom_time: datetime | None = None

    @model_validator(mode="after")
    def validate_geometry(self) -> DarvasBox:
        if self.upper < self.lower:
            raise ValueError("Darvas upper box must be >= lower box")
        return self

    @property
    def height(self) -> float:
        return self.upper - self.lower

    @property
    def mid(self) -> float:
        return (self.upper + self.lower) / 2.0


class DarvasBoxSnapshot(BaseModel):
    """Latest Darvas detection result for strategy consumers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: DarvasBoxState
    box: DarvasBox | None = None
    prior_box: DarvasBox | None = None
    consolidating: bool = False
    breakout: bool = False
    breakdown: bool = False
    new_box_formation: bool = False
    close: float
    bar_index: int = Field(..., ge=0)
    reasons: list[str] = Field(default_factory=list)
