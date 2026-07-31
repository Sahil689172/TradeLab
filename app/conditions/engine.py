"""Reusable condition evaluation engine."""

from __future__ import annotations

from app.conditions import operators as ops
from app.conditions.exceptions import ConditionValidationError
from app.conditions.schemas import (
    BreakCondition,
    CompareCondition,
    ComparisonOperator,
    ConditionResult,
    ConditionSpec,
    CrossCondition,
    LogicCondition,
    LogicOperator,
    MarketOperator,
    RangeCondition,
    RetestCondition,
    RetestSide,
    TouchCondition,
)

ENGINE_VERSION = "1.0.0"


class ConditionEngine:
    """Evaluate comparison, market, and boolean conditions.

    Returns strongly typed ``ConditionResult`` values with ``value`` (True/False)
    and a human-readable ``reason``. Contains no strategy logic.
    """

    @property
    def version(self) -> str:
        return ENGINE_VERSION

    def evaluate(self, condition: ConditionSpec) -> ConditionResult:
        """Evaluate a declarative condition tree."""
        if isinstance(condition, CompareCondition):
            return self.compare(
                condition.left,
                condition.operator,
                condition.right,
                left_label=condition.left_label,
                right_label=condition.right_label,
            )
        if isinstance(condition, CrossCondition):
            if condition.operator == MarketOperator.CROSS_ABOVE.value:
                return self.cross_above(
                    condition.left_previous,
                    condition.left_current,
                    condition.right_previous,
                    condition.right_current,
                    left_label=condition.left_label,
                    right_label=condition.right_label,
                )
            return self.cross_below(
                condition.left_previous,
                condition.left_current,
                condition.right_previous,
                condition.right_current,
                left_label=condition.left_label,
                right_label=condition.right_label,
            )
        if isinstance(condition, TouchCondition):
            return self.touches(
                condition.low,
                condition.high,
                condition.level,
                tolerance=condition.tolerance,
                level_label=condition.level_label,
            )
        if isinstance(condition, BreakCondition):
            if condition.operator == MarketOperator.BREAKS_ABOVE.value:
                return self.breaks_above(
                    condition.previous_close,
                    condition.current_close,
                    condition.level,
                    level_label=condition.level_label,
                )
            return self.breaks_below(
                condition.previous_close,
                condition.current_close,
                condition.level,
                level_label=condition.level_label,
            )
        if isinstance(condition, RetestCondition):
            return self.retest(
                side=condition.side,
                low=condition.low,
                high=condition.high,
                close=condition.close,
                level=condition.level,
                tolerance=condition.tolerance,
                level_label=condition.level_label,
            )
        if isinstance(condition, RangeCondition):
            if condition.operator == MarketOperator.INSIDE_RANGE.value:
                return self.inside_range(
                    condition.value,
                    condition.lower,
                    condition.upper,
                    value_label=condition.value_label,
                )
            return self.outside_range(
                condition.value,
                condition.lower,
                condition.upper,
                value_label=condition.value_label,
            )
        if isinstance(condition, LogicCondition):
            nested = [self.evaluate(child) for child in condition.conditions]
            if condition.operator is LogicOperator.AND:
                return self.logic_and(nested)
            if condition.operator is LogicOperator.OR:
                return self.logic_or(nested)
            return self.logic_not(nested[0])

        raise ConditionValidationError(f"Unsupported condition type: {type(condition)!r}")

    def compare(
        self,
        left: float,
        operator: ComparisonOperator | str,
        right: float,
        *,
        left_label: str = "left",
        right_label: str = "right",
    ) -> ConditionResult:
        return ops.compare(
            left,
            _as_comparison_operator(operator),
            right,
            left_label=left_label,
            right_label=right_label,
        )

    def cross_above(
        self,
        left_previous: float,
        left_current: float,
        right_previous: float,
        right_current: float,
        *,
        left_label: str = "left",
        right_label: str = "right",
    ) -> ConditionResult:
        return ops.cross_above(
            left_previous,
            left_current,
            right_previous,
            right_current,
            left_label=left_label,
            right_label=right_label,
        )

    def cross_below(
        self,
        left_previous: float,
        left_current: float,
        right_previous: float,
        right_current: float,
        *,
        left_label: str = "left",
        right_label: str = "right",
    ) -> ConditionResult:
        return ops.cross_below(
            left_previous,
            left_current,
            right_previous,
            right_current,
            left_label=left_label,
            right_label=right_label,
        )

    def touches(
        self,
        low: float,
        high: float,
        level: float,
        *,
        tolerance: float = 0.0,
        level_label: str = "level",
    ) -> ConditionResult:
        return ops.touches(
            low,
            high,
            level,
            tolerance=tolerance,
            level_label=level_label,
        )

    def breaks_above(
        self,
        previous_close: float,
        current_close: float,
        level: float,
        *,
        level_label: str = "level",
    ) -> ConditionResult:
        return ops.breaks_above(
            previous_close,
            current_close,
            level,
            level_label=level_label,
        )

    def breaks_below(
        self,
        previous_close: float,
        current_close: float,
        level: float,
        *,
        level_label: str = "level",
    ) -> ConditionResult:
        return ops.breaks_below(
            previous_close,
            current_close,
            level,
            level_label=level_label,
        )

    def retest(
        self,
        *,
        side: RetestSide | str,
        low: float,
        high: float,
        close: float,
        level: float,
        tolerance: float = 0.0,
        level_label: str = "level",
    ) -> ConditionResult:
        return ops.retest(
            side=_as_retest_side(side),
            low=low,
            high=high,
            close=close,
            level=level,
            tolerance=tolerance,
            level_label=level_label,
        )

    def inside_range(
        self,
        value: float,
        lower: float,
        upper: float,
        *,
        value_label: str = "value",
    ) -> ConditionResult:
        return ops.inside_range(value, lower, upper, value_label=value_label)

    def outside_range(
        self,
        value: float,
        lower: float,
        upper: float,
        *,
        value_label: str = "value",
    ) -> ConditionResult:
        return ops.outside_range(value, lower, upper, value_label=value_label)

    def logic_and(self, results: list[ConditionResult]) -> ConditionResult:
        return ops.logic_and(results)

    def logic_or(self, results: list[ConditionResult]) -> ConditionResult:
        return ops.logic_or(results)

    def logic_not(self, result: ConditionResult) -> ConditionResult:
        return ops.logic_not(result)


def _as_comparison_operator(operator: ComparisonOperator | str) -> ComparisonOperator:
    if isinstance(operator, ComparisonOperator):
        return operator
    try:
        return ComparisonOperator(operator)
    except ValueError as exc:
        raise ConditionValidationError(f"Unknown comparison operator: {operator!r}") from exc


def _as_retest_side(side: RetestSide | str) -> RetestSide:
    if isinstance(side, RetestSide):
        return side
    try:
        return RetestSide(side)
    except ValueError as exc:
        raise ConditionValidationError(f"Unknown retest side: {side!r}") from exc
