"""Unit tests for the condition engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.conditions import (
    BreakCondition,
    CompareCondition,
    ComparisonOperator,
    ConditionEngine,
    ConditionResult,
    CrossCondition,
    LogicCondition,
    LogicOperator,
    MarketOperator,
    RangeCondition,
    RetestCondition,
    RetestSide,
    TouchCondition,
)


@pytest.fixture
def engine() -> ConditionEngine:
    return ConditionEngine()


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "operator", "right", "expected"),
    [
        (5.0, ComparisonOperator.GT, 3.0, True),
        (5.0, ComparisonOperator.GT, 5.0, False),
        (3.0, ComparisonOperator.LT, 5.0, True),
        (5.0, ComparisonOperator.GTE, 5.0, True),
        (5.0, ComparisonOperator.LTE, 4.0, False),
        (5.0, ComparisonOperator.EQ, 5.0, True),
        (5.0, ">", 4.0, True),
    ],
)
def test_compare_operators(
    engine: ConditionEngine,
    left: float,
    operator: ComparisonOperator | str,
    right: float,
    expected: bool,
) -> None:
    result = engine.compare(left, operator, right, left_label="close", right_label="level")

    assert result.value is expected
    assert result.is_true is expected
    assert "close" in result.reason
    assert result.operator in {">", "<", ">=", "<=", "=="}


# ---------------------------------------------------------------------------
# Cross / Break / Touch / Retest / Range
# ---------------------------------------------------------------------------


def test_cross_above_true(engine: ConditionEngine) -> None:
    result = engine.cross_above(9.0, 11.0, 10.0, 10.0, left_label="close", right_label="EMA")

    assert result.value is True
    assert result.operator == MarketOperator.CROSS_ABOVE.value


def test_cross_above_false_when_already_above(engine: ConditionEngine) -> None:
    result = engine.cross_above(11.0, 12.0, 10.0, 10.0)

    assert result.value is False


def test_cross_below_true(engine: ConditionEngine) -> None:
    result = engine.cross_below(11.0, 9.0, 10.0, 10.0)

    assert result.value is True
    assert result.operator == MarketOperator.CROSS_BELOW.value


def test_touches_when_level_inside_bar(engine: ConditionEngine) -> None:
    result = engine.touches(low=98.0, high=102.0, level=100.0, level_label="PDH")

    assert result.value is True
    assert result.operator == MarketOperator.TOUCHES.value


def test_touches_with_tolerance(engine: ConditionEngine) -> None:
    result = engine.touches(low=101.0, high=103.0, level=100.0, tolerance=1.0)

    assert result.value is True


def test_breaks_above_true(engine: ConditionEngine) -> None:
    result = engine.breaks_above(99.0, 101.0, 100.0, level_label="ORH")

    assert result.value is True
    assert result.operator == MarketOperator.BREAKS_ABOVE.value


def test_breaks_below_true(engine: ConditionEngine) -> None:
    result = engine.breaks_below(101.0, 99.0, 100.0)

    assert result.value is True
    assert result.operator == MarketOperator.BREAKS_BELOW.value


def test_retest_above_requires_touch_and_close_on_side(engine: ConditionEngine) -> None:
    ok = engine.retest(
        side=RetestSide.ABOVE,
        low=99.5,
        high=102.0,
        close=100.5,
        level=100.0,
    )
    fail_close = engine.retest(
        side=RetestSide.ABOVE,
        low=99.5,
        high=102.0,
        close=99.7,
        level=100.0,
    )

    assert ok.value is True
    assert fail_close.value is False
    assert ok.operator == MarketOperator.RETEST.value


def test_retest_below(engine: ConditionEngine) -> None:
    result = engine.retest(
        side="BELOW",
        low=98.0,
        high=100.5,
        close=99.5,
        level=100.0,
    )

    assert result.value is True


def test_inside_and_outside_range(engine: ConditionEngine) -> None:
    inside = engine.inside_range(105.0, 100.0, 110.0, value_label="close")
    outside = engine.outside_range(95.0, 100.0, 110.0, value_label="close")
    not_outside = engine.outside_range(105.0, 100.0, 110.0)

    assert inside.value is True
    assert outside.value is True
    assert not_outside.value is False
    assert inside.operator == MarketOperator.INSIDE_RANGE.value
    assert outside.operator == MarketOperator.OUTSIDE_RANGE.value


# ---------------------------------------------------------------------------
# Boolean logic
# ---------------------------------------------------------------------------


def test_logic_and_or_not(engine: ConditionEngine) -> None:
    a = engine.compare(5, ">", 3)
    b = engine.compare(2, "<", 1)
    c = engine.compare(4, "==", 4)

    assert engine.logic_and([a, c]).value is True
    assert engine.logic_and([a, b]).value is False
    assert engine.logic_or([a, b]).value is True
    assert engine.logic_or([b, b]).value is False
    assert engine.logic_not(b).value is True
    assert engine.logic_not(a).value is False


# ---------------------------------------------------------------------------
# Declarative evaluate()
# ---------------------------------------------------------------------------


def test_evaluate_compare_tree(engine: ConditionEngine) -> None:
    result = engine.evaluate(
        CompareCondition(
            operator=ComparisonOperator.GTE,
            left=101.0,
            right=100.0,
            left_label="close",
            right_label="pivot",
        ),
    )

    assert result.value is True
    assert "close" in result.reason


def test_evaluate_nested_logic(engine: ConditionEngine) -> None:
    tree = LogicCondition(
        operator=LogicOperator.AND,
        conditions=[
            CompareCondition(operator=ComparisonOperator.GT, left=110.0, right=100.0),
            LogicCondition(
                operator=LogicOperator.OR,
                conditions=[
                    CrossCondition(
                        operator="CROSS_ABOVE",
                        left_previous=99.0,
                        left_current=101.0,
                        right_previous=100.0,
                        right_current=100.0,
                    ),
                    RangeCondition(
                        operator="INSIDE_RANGE",
                        value=105.0,
                        lower=100.0,
                        upper=110.0,
                    ),
                ],
            ),
            LogicCondition(
                operator=LogicOperator.NOT,
                conditions=[
                    BreakCondition(
                        operator="BREAKS_BELOW",
                        previous_close=101.0,
                        current_close=99.0,
                        level=100.0,
                    ),
                ],
            ),
        ],
    )

    result = engine.evaluate(tree)

    # AND(True, OR(True, True)=True, NOT(True)=False) => False
    assert result.value is False
    assert result.operator == LogicOperator.AND.value


def test_evaluate_market_conditions(engine: ConditionEngine) -> None:
    touch = engine.evaluate(
        TouchCondition(low=99.0, high=101.0, level=100.0, level_label="S1"),
    )
    retest = engine.evaluate(
        RetestCondition(
            side=RetestSide.ABOVE,
            low=99.5,
            high=101.0,
            close=100.2,
            level=100.0,
        ),
    )
    brk = engine.evaluate(
        BreakCondition(
            operator="BREAKS_ABOVE",
            previous_close=99.0,
            current_close=101.0,
            level=100.0,
        ),
    )

    assert touch.value is True
    assert retest.value is True
    assert brk.value is True


def test_condition_result_is_frozen() -> None:
    result = ConditionResult(value=True, reason="ok", operator=">")
    with pytest.raises(ValidationError):
        result.value = False  # type: ignore[misc]


def test_logic_condition_arity_validation() -> None:
    with pytest.raises(ValidationError):
        LogicCondition(
            operator=LogicOperator.NOT,
            conditions=[
                CompareCondition(operator=ComparisonOperator.GT, left=1, right=0),
                CompareCondition(operator=ComparisonOperator.GT, left=2, right=0),
            ],
        )
    with pytest.raises(ValidationError):
        LogicCondition(
            operator=LogicOperator.AND,
            conditions=[CompareCondition(operator=ComparisonOperator.GT, left=1, right=0)],
        )
