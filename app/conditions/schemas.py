"""Pydantic contracts for reusable condition evaluation."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonOperator(str, Enum):
    """Scalar comparison operators."""

    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    EQ = "=="


class MarketOperator(str, Enum):
    """Price-action style operators over bar context."""

    CROSS_ABOVE = "CROSS_ABOVE"
    CROSS_BELOW = "CROSS_BELOW"
    TOUCHES = "TOUCHES"
    BREAKS_ABOVE = "BREAKS_ABOVE"
    BREAKS_BELOW = "BREAKS_BELOW"
    RETEST = "RETEST"
    INSIDE_RANGE = "INSIDE_RANGE"
    OUTSIDE_RANGE = "OUTSIDE_RANGE"


class LogicOperator(str, Enum):
    """Boolean combinators."""

    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class RetestSide(str, Enum):
    """Direction of the prior break that a retest confirms."""

    ABOVE = "ABOVE"
    BELOW = "BELOW"


class ConditionResult(BaseModel):
    """Outcome of evaluating a single condition or expression tree."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: bool
    reason: str = Field(..., min_length=1)
    operator: str | None = None

    @property
    def is_true(self) -> bool:
        return self.value

    @property
    def is_false(self) -> bool:
        return not self.value


class CompareCondition(BaseModel):
    """Compare two scalar values: left <op> right."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["compare"] = "compare"
    operator: ComparisonOperator
    left: float
    right: float
    left_label: str = "left"
    right_label: str = "right"


class CrossCondition(BaseModel):
    """Detect a cross between two series using previous and current values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["cross"] = "cross"
    operator: Literal["CROSS_ABOVE", "CROSS_BELOW"]
    left_previous: float
    left_current: float
    right_previous: float
    right_current: float
    left_label: str = "left"
    right_label: str = "right"


class TouchCondition(BaseModel):
    """True when a bar's range touches a level within tolerance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["touch"] = "touch"
    low: float = Field(..., gt=0.0)
    high: float = Field(..., gt=0.0)
    level: float = Field(..., gt=0.0)
    tolerance: float = Field(default=0.0, ge=0.0)
    level_label: str = "level"

    @model_validator(mode="after")
    def validate_range(self) -> TouchCondition:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        return self


class BreakCondition(BaseModel):
    """True when close breaks a level relative to the previous close."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["break"] = "break"
    operator: Literal["BREAKS_ABOVE", "BREAKS_BELOW"]
    previous_close: float = Field(..., gt=0.0)
    current_close: float = Field(..., gt=0.0)
    level: float = Field(..., gt=0.0)
    level_label: str = "level"


class RetestCondition(BaseModel):
    """True when price returns to touch a previously broken level from the break side."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["retest"] = "retest"
    side: RetestSide
    low: float = Field(..., gt=0.0)
    high: float = Field(..., gt=0.0)
    close: float = Field(..., gt=0.0)
    level: float = Field(..., gt=0.0)
    tolerance: float = Field(default=0.0, ge=0.0)
    level_label: str = "level"

    @model_validator(mode="after")
    def validate_bar(self) -> RetestCondition:
        if self.high < self.low:
            raise ValueError("high must be >= low")
        if not (self.low <= self.close <= self.high):
            raise ValueError("close must be within [low, high]")
        return self


class RangeCondition(BaseModel):
    """True when a value is inside or outside an inclusive [lower, upper] range."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["range"] = "range"
    operator: Literal["INSIDE_RANGE", "OUTSIDE_RANGE"]
    value: float
    lower: float
    upper: float
    value_label: str = "value"

    @model_validator(mode="after")
    def validate_bounds(self) -> RangeCondition:
        if self.upper < self.lower:
            raise ValueError("upper must be >= lower")
        return self


class LogicCondition(BaseModel):
    """AND / OR / NOT composition of nested conditions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["logic"] = "logic"
    operator: LogicOperator
    conditions: list[ConditionSpec] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_arity(self) -> LogicCondition:
        if self.operator is LogicOperator.NOT and len(self.conditions) != 1:
            raise ValueError("NOT requires exactly one nested condition")
        if self.operator in (LogicOperator.AND, LogicOperator.OR) and len(self.conditions) < 2:
            raise ValueError(f"{self.operator.value} requires at least two nested conditions")
        return self


ConditionSpec = Annotated[
    Union[
        CompareCondition,
        CrossCondition,
        TouchCondition,
        BreakCondition,
        RetestCondition,
        RangeCondition,
        LogicCondition,
    ],
    Field(discriminator="type"),
]

LogicCondition.model_rebuild()
