"""Unit tests for Phase A4X.1 Strategy Filter Framework (no concrete filters)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.strategy_engine.filters import (
    BaseStrategyFilter,
    FilterNotFoundError,
    FilterPipeline,
    FilterPipelineError,
    FilterRegistrationError,
    FilterRegistry,
    FilterValidationError,
    StrategyRecommendation,
)
from app.strategy_engine.models import SignalType, TradePlan


def _rec(
    *,
    confidence: float = 0.8,
    signal: SignalType = SignalType.BUY,
    notes: list[str] | None = None,
) -> StrategyRecommendation:
    return StrategyRecommendation(
        strategy_name="stub",
        symbol="RELIANCE",
        timestamp=datetime(2022, 6, 1, tzinfo=timezone.utc),
        signal=signal,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit_1=110.0,
        take_profit_2=120.0,
        holding_period=10,
        risk_reward=2.0,
        confidence=confidence,
        reasons=["unit test"],
        filter_notes=notes or [],
    )


class _AnnotatingFilter(BaseStrategyFilter):
    """Test double — appends a note; not a production filter."""

    def __init__(self, *, name: str, priority: int = 100, enabled: bool = True, tag: str = "ok") -> None:
        super().__init__(name=name, enabled=enabled, priority=priority)
        self.tag = tag
        self.validate_calls = 0
        self.apply_calls = 0

    def validate(self, recommendation: StrategyRecommendation) -> None:
        self.validate_calls += 1
        if recommendation.rejected:
            raise FilterValidationError("already rejected")

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        self.apply_calls += 1
        return recommendation.model_copy(
            update={"filter_notes": [*recommendation.filter_notes, f"{self.name}:{self.tag}"]},
        )


class _RejectingFilter(BaseStrategyFilter):
    def validate(self, recommendation: StrategyRecommendation) -> None:
        if recommendation.confidence < 0.9:
            raise FilterValidationError("confidence too low")

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        return recommendation


class _BoostConfidenceFilter(BaseStrategyFilter):
    def validate(self, recommendation: StrategyRecommendation) -> None:
        return None

    def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
        return recommendation.model_copy(
            update={"confidence": min(1.0, recommendation.confidence + 0.05)},
        )


def test_base_filter_contract_properties() -> None:
    filt = _AnnotatingFilter(name="alpha", priority=10, enabled=True)
    assert filt.name == "alpha"
    assert filt.enabled is True
    assert filt.priority == 10
    filt.disable()
    assert filt.enabled is False
    filt.enable()
    assert filt.enabled is True
    filt.priority = 5
    assert filt.priority == 5


def test_blank_filter_name_rejected() -> None:
    with pytest.raises(FilterRegistrationError):
        _AnnotatingFilter(name="  ")


def test_registry_register_get_list() -> None:
    registry = FilterRegistry()
    a = _AnnotatingFilter(name="a", priority=20)
    b = _AnnotatingFilter(name="b", priority=10, enabled=False)
    registry.register(a)
    registry.register(b)
    assert registry.list_names() == ["a", "b"]
    assert registry.get("a") is a
    assert [f.name for f in registry.list_enabled()] == ["a"]
    registry.unregister("b")
    assert registry.list_names() == ["a"]


def test_registry_duplicate_and_missing() -> None:
    registry = FilterRegistry([_AnnotatingFilter(name="dup")])
    with pytest.raises(FilterRegistrationError):
        registry.register(_AnnotatingFilter(name="dup"))
    with pytest.raises(FilterNotFoundError):
        registry.get("missing")


def test_registry_constructor_injection() -> None:
    filters = [
        _AnnotatingFilter(name="late", priority=50),
        _AnnotatingFilter(name="early", priority=1),
    ]
    registry = FilterRegistry(filters)
    assert [f.name for f in registry.list_enabled()] == ["early", "late"]


def test_pipeline_runs_enabled_filters_in_priority_order() -> None:
    first = _AnnotatingFilter(name="first", priority=1, tag="1")
    second = _AnnotatingFilter(name="second", priority=2, tag="2")
    disabled = _AnnotatingFilter(name="off", priority=0, enabled=False, tag="x")
    pipeline = FilterPipeline(filters=[second, disabled, first])

    result = pipeline.run(_rec())
    assert result.filters_applied == 2
    assert result.filters_skipped == 1
    assert result.output.filter_notes == ["first:1", "second:2"]
    assert first.apply_calls == 1
    assert second.apply_calls == 1
    assert disabled.apply_calls == 0
    assert [s.filter_name for s in result.steps if s.applied] == ["first", "second"]


def test_pipeline_via_registry_di() -> None:
    registry = FilterRegistry()
    registry.register(_BoostConfidenceFilter(name="boost", priority=10))
    registry.register(_AnnotatingFilter(name="note", priority=20, tag="n"))
    pipeline = FilterPipeline(registry)

    out = pipeline.apply(_rec(confidence=0.80))
    assert out.confidence == pytest.approx(0.85)
    assert out.filter_notes == ["note:n"]


def test_pipeline_stop_on_validation_failure() -> None:
    reject = _RejectingFilter(name="gate", priority=1)
    later = _AnnotatingFilter(name="later", priority=2, tag="should-not-run")
    pipeline = FilterPipeline(filters=[reject, later], stop_on_rejection=True)

    result = pipeline.run(_rec(confidence=0.5))
    assert result.output.rejected is True
    assert "confidence too low" in result.output.rejection_reason
    assert later.apply_calls == 0
    assert result.filters_applied == 0


def test_pipeline_continue_when_stop_on_rejection_false() -> None:
    class _SoftReject(BaseStrategyFilter):
        def validate(self, recommendation: StrategyRecommendation) -> None:
            return None

        def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
            return recommendation.model_copy(
                update={
                    "rejected": True,
                    "rejection_reason": "soft reject",
                    "filter_notes": [*recommendation.filter_notes, "soft"],
                },
            )

    class _AlwaysAnnotate(BaseStrategyFilter):
        def validate(self, recommendation: StrategyRecommendation) -> None:
            return None

        def apply(self, recommendation: StrategyRecommendation) -> StrategyRecommendation:
            return recommendation.model_copy(
                update={"filter_notes": [*recommendation.filter_notes, "after"]},
            )

    pipeline = FilterPipeline(
        filters=[
            _SoftReject(name="soft", priority=1),
            _AlwaysAnnotate(name="after", priority=2),
        ],
        stop_on_rejection=False,
    )
    result = pipeline.run(_rec())
    assert result.output.rejected is True
    assert result.output.filter_notes == ["soft", "after"]
    assert result.filters_applied == 2


def test_pipeline_rejects_both_registry_and_filters() -> None:
    with pytest.raises(FilterPipelineError):
        FilterPipeline(
            FilterRegistry(),
            filters=[_AnnotatingFilter(name="x")],
        )


def test_pipeline_empty_registry_passthrough() -> None:
    pipeline = FilterPipeline(FilterRegistry())
    rec = _rec()
    result = pipeline.run(rec)
    assert result.output == rec
    assert result.filters_applied == 0


def test_strategy_recommendation_from_trade_plan() -> None:
    plan = TradePlan(
        symbol="tcs",
        entry_price=100.0,
        signal=SignalType.HOLD,
        stop_loss=95.0,
        take_profit_1=105.0,
        take_profit_2=110.0,
        holding_period=5,
        risk_reward=1.0,
        confidence=0.6,
        reasons=["from plan"],
        strategy_name="ema_trend",
    )
    rec = StrategyRecommendation.from_trade_plan(plan)
    assert rec.symbol == "TCS"
    assert rec.strategy_name == "ema_trend"
    assert rec.signal is SignalType.HOLD


def test_filters_are_chainable_and_strategy_agnostic() -> None:
    """Strategies never import filters — pipeline consumes test doubles only."""
    pipeline = FilterPipeline(
        filters=[
            _BoostConfidenceFilter(name="boost", priority=1),
            _AnnotatingFilter(name="tag", priority=2, tag="done"),
        ],
    )
    out = pipeline.apply(_rec(confidence=0.7))
    assert out.confidence == pytest.approx(0.75)
    assert out.filter_notes[-1] == "tag:done"


def test_protocol_runtime_check() -> None:
    from app.strategy_engine.filters.protocols import StrategyFilterPort

    filt = _AnnotatingFilter(name="proto")
    assert isinstance(filt, StrategyFilterPort)
