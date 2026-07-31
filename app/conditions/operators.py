"""Pure deterministic condition operators."""

from __future__ import annotations

from app.conditions.schemas import (
    ComparisonOperator,
    ConditionResult,
    LogicOperator,
    MarketOperator,
    RetestSide,
)


def compare(
    left: float,
    operator: ComparisonOperator,
    right: float,
    *,
    left_label: str = "left",
    right_label: str = "right",
) -> ConditionResult:
    """Evaluate a scalar comparison."""
    ops = {
        ComparisonOperator.GT: left > right,
        ComparisonOperator.LT: left < right,
        ComparisonOperator.GTE: left >= right,
        ComparisonOperator.LTE: left <= right,
        ComparisonOperator.EQ: left == right,
    }
    value = ops[operator]
    return ConditionResult(
        value=value,
        operator=operator.value,
        reason=(
            f"{left_label} ({_fmt(left)}) {operator.value} {right_label} ({_fmt(right)}) "
            f"is {value}"
        ),
    )


def cross_above(
    left_previous: float,
    left_current: float,
    right_previous: float,
    right_current: float,
    *,
    left_label: str = "left",
    right_label: str = "right",
) -> ConditionResult:
    """True when left crosses from at/below right to strictly above right."""
    value = left_previous <= right_previous and left_current > right_current
    return ConditionResult(
        value=value,
        operator=MarketOperator.CROSS_ABOVE.value,
        reason=(
            f"{left_label} cross above {right_label}: "
            f"prev {_fmt(left_previous)}/{_fmt(right_previous)}, "
            f"curr {_fmt(left_current)}/{_fmt(right_current)} -> {value}"
        ),
    )


def cross_below(
    left_previous: float,
    left_current: float,
    right_previous: float,
    right_current: float,
    *,
    left_label: str = "left",
    right_label: str = "right",
) -> ConditionResult:
    """True when left crosses from at/above right to strictly below right."""
    value = left_previous >= right_previous and left_current < right_current
    return ConditionResult(
        value=value,
        operator=MarketOperator.CROSS_BELOW.value,
        reason=(
            f"{left_label} cross below {right_label}: "
            f"prev {_fmt(left_previous)}/{_fmt(right_previous)}, "
            f"curr {_fmt(left_current)}/{_fmt(right_current)} -> {value}"
        ),
    )


def touches(
    low: float,
    high: float,
    level: float,
    *,
    tolerance: float = 0.0,
    level_label: str = "level",
) -> ConditionResult:
    """True when [low - tol, high + tol] intersects the level."""
    if high < low:
        raise ValueError("high must be >= low")
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    value = (low - tolerance) <= level <= (high + tolerance)
    return ConditionResult(
        value=value,
        operator=MarketOperator.TOUCHES.value,
        reason=(
            f"bar [{_fmt(low)}, {_fmt(high)}] touches {level_label} ({_fmt(level)}) "
            f"tol={_fmt(tolerance)} -> {value}"
        ),
    )


def breaks_above(
    previous_close: float,
    current_close: float,
    level: float,
    *,
    level_label: str = "level",
) -> ConditionResult:
    """True when prior close was at/below level and current close is strictly above."""
    value = previous_close <= level < current_close
    return ConditionResult(
        value=value,
        operator=MarketOperator.BREAKS_ABOVE.value,
        reason=(
            f"close breaks above {level_label} ({_fmt(level)}): "
            f"prev={_fmt(previous_close)} curr={_fmt(current_close)} -> {value}"
        ),
    )


def breaks_below(
    previous_close: float,
    current_close: float,
    level: float,
    *,
    level_label: str = "level",
) -> ConditionResult:
    """True when prior close was at/above level and current close is strictly below."""
    value = previous_close >= level > current_close
    return ConditionResult(
        value=value,
        operator=MarketOperator.BREAKS_BELOW.value,
        reason=(
            f"close breaks below {level_label} ({_fmt(level)}): "
            f"prev={_fmt(previous_close)} curr={_fmt(current_close)} -> {value}"
        ),
    )


def retest(
    *,
    side: RetestSide,
    low: float,
    high: float,
    close: float,
    level: float,
    tolerance: float = 0.0,
    level_label: str = "level",
) -> ConditionResult:
    """True when price revisits a broken level while remaining on the break side.

    ABOVE: bullish retest after a break above — bar touches level and close >= level.
    BELOW: bearish retest after a break below — bar touches level and close <= level.
    """
    touched = touches(
        low,
        high,
        level,
        tolerance=tolerance,
        level_label=level_label,
    )
    if side is RetestSide.ABOVE:
        held = close >= level
        value = touched.value and held
        side_text = "above"
    else:
        held = close <= level
        value = touched.value and held
        side_text = "below"

    return ConditionResult(
        value=value,
        operator=MarketOperator.RETEST.value,
        reason=(
            f"retest {side_text} {level_label} ({_fmt(level)}): "
            f"touch={touched.value} close={_fmt(close)} held_side={held} -> {value}"
        ),
    )


def inside_range(
    value: float,
    lower: float,
    upper: float,
    *,
    value_label: str = "value",
) -> ConditionResult:
    """True when lower <= value <= upper."""
    if upper < lower:
        raise ValueError("upper must be >= lower")
    result = lower <= value <= upper
    return ConditionResult(
        value=result,
        operator=MarketOperator.INSIDE_RANGE.value,
        reason=(
            f"{value_label} ({_fmt(value)}) inside [{_fmt(lower)}, {_fmt(upper)}] -> {result}"
        ),
    )


def outside_range(
    value: float,
    lower: float,
    upper: float,
    *,
    value_label: str = "value",
) -> ConditionResult:
    """True when value < lower or value > upper."""
    if upper < lower:
        raise ValueError("upper must be >= lower")
    result = value < lower or value > upper
    return ConditionResult(
        value=result,
        operator=MarketOperator.OUTSIDE_RANGE.value,
        reason=(
            f"{value_label} ({_fmt(value)}) outside [{_fmt(lower)}, {_fmt(upper)}] -> {result}"
        ),
    )


def logic_and(results: list[ConditionResult]) -> ConditionResult:
    """True when every nested result is true."""
    if len(results) < 2:
        raise ValueError("AND requires at least two nested results")
    value = all(item.value for item in results)
    parts = "; ".join(item.reason for item in results)
    return ConditionResult(
        value=value,
        operator=LogicOperator.AND.value,
        reason=f"AND -> {value} | {parts}",
    )


def logic_or(results: list[ConditionResult]) -> ConditionResult:
    """True when any nested result is true."""
    if len(results) < 2:
        raise ValueError("OR requires at least two nested results")
    value = any(item.value for item in results)
    parts = "; ".join(item.reason for item in results)
    return ConditionResult(
        value=value,
        operator=LogicOperator.OR.value,
        reason=f"OR -> {value} | {parts}",
    )


def logic_not(result: ConditionResult) -> ConditionResult:
    """Invert a nested result."""
    value = not result.value
    return ConditionResult(
        value=value,
        operator=LogicOperator.NOT.value,
        reason=f"NOT -> {value} | {result.reason}",
    )


def _fmt(value: float) -> str:
    return f"{value:.6g}"
