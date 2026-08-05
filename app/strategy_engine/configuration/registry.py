"""Registry binding strategy_name → native config class + builder."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.configuration.exceptions import (
    StrategyConfigNotFoundError,
    StrategyConfigValidationError,
)
from app.strategy_engine.configuration.schemas import StrategySystemConfig

NativeBuilder = Callable[[BaseModel], BaseStrategy]


class StrategyConfigBinding:
    """Maps a strategy name to its native pydantic config + factory."""

    def __init__(
        self,
        *,
        strategy_name: str,
        config_cls: type[BaseModel],
        builder: NativeBuilder,
    ) -> None:
        self.strategy_name = strategy_name
        self.config_cls = config_cls
        self.builder = builder

    def build_native_config(self, system: StrategySystemConfig) -> BaseModel:
        if system.strategy_name != self.strategy_name:
            raise StrategyConfigValidationError(
                f"Config strategy_name '{system.strategy_name}' does not match "
                f"binding '{self.strategy_name}'",
            )
        payload = system.flattened_native_payload()
        # Drop keys the native model does not accept (extra=forbid on most configs)
        allowed = set(self.config_cls.model_fields.keys())
        filtered = {key: value for key, value in payload.items() if key in allowed}
        try:
            return self.config_cls.model_validate(filtered)
        except ValidationError as exc:
            raise StrategyConfigValidationError(
                f"Invalid configuration for '{self.strategy_name}': {exc}",
            ) from exc

    def build_strategy(self, system: StrategySystemConfig) -> BaseStrategy:
        if not system.enabled:
            raise StrategyConfigValidationError(
                f"Strategy '{self.strategy_name}' is disabled in configuration",
            )
        native = self.build_native_config(system)
        return self.builder(native)


_BINDINGS: dict[str, StrategyConfigBinding] = {}


def register_binding(binding: StrategyConfigBinding) -> None:
    _BINDINGS[binding.strategy_name] = binding


def get_binding(strategy_name: str) -> StrategyConfigBinding:
    key = strategy_name.strip()
    try:
        return _BINDINGS[key]
    except KeyError as exc:
        known = ", ".join(sorted(_BINDINGS)) or "(none registered)"
        raise StrategyConfigNotFoundError(
            f"No configuration binding for '{key}'. Known: {known}",
        ) from exc


def list_bound_strategies() -> list[str]:
    ensure_default_bindings()
    return list(_BINDINGS.keys())


def ensure_default_bindings() -> None:
    """Lazily register all 12 strategy bindings (idempotent)."""
    if _BINDINGS:
        return

    from app.strategies.break_retest.config import BreakRetestStrategyConfig
    from app.strategies.break_retest.strategy import BreakRetestStrategy
    from app.strategies.cpr.config import CPRStrategyConfig
    from app.strategies.cpr.strategy import CPRStrategy
    from app.strategies.darvas_box.config import DarvasBoxStrategyConfig
    from app.strategies.darvas_box.strategy import DarvasBoxStrategy
    from app.strategies.donchian.config import DonchianStrategyConfig
    from app.strategies.donchian.strategy import DonchianStrategy
    from app.strategies.ema_trend.config import EMATrendConfig
    from app.strategies.ema_trend.strategy import EMATrendStrategy
    from app.strategies.momentum.config import MomentumConfig
    from app.strategies.momentum.strategy import MomentumStrategy
    from app.strategies.opening_range_breakout.config import OpeningRangeBreakoutConfig
    from app.strategies.opening_range_breakout.strategy import OpeningRangeBreakoutStrategy
    from app.strategies.previous_day_breakout.config import PreviousDayBreakoutConfig
    from app.strategies.previous_day_breakout.strategy import PreviousDayBreakoutStrategy
    from app.strategies.relative_strength.config import RelativeStrengthConfig
    from app.strategies.relative_strength.strategy import RelativeStrengthStrategy
    from app.strategies.supertrend.config import SuperTrendStrategyConfig
    from app.strategies.supertrend.strategy import SuperTrendStrategy
    from app.strategies.volume_breakout.config import VolumeBreakoutConfig
    from app.strategies.volume_breakout.strategy import VolumeBreakoutStrategy
    from app.strategies.vwap.config import VWAPStrategyConfig
    from app.strategies.vwap.strategy import VWAPStrategy

    specs: list[tuple[str, type[BaseModel], NativeBuilder]] = [
        ("ema_trend", EMATrendConfig, lambda c: EMATrendStrategy(c)),  # type: ignore[arg-type]
        ("opening_range_breakout", OpeningRangeBreakoutConfig, lambda c: OpeningRangeBreakoutStrategy(c)),  # type: ignore[arg-type]
        ("vwap", VWAPStrategyConfig, lambda c: VWAPStrategy(c)),  # type: ignore[arg-type]
        ("supertrend", SuperTrendStrategyConfig, lambda c: SuperTrendStrategy(c)),  # type: ignore[arg-type]
        ("momentum", MomentumConfig, lambda c: MomentumStrategy(c)),  # type: ignore[arg-type]
        ("break_retest", BreakRetestStrategyConfig, lambda c: BreakRetestStrategy(c)),  # type: ignore[arg-type]
        ("cpr", CPRStrategyConfig, lambda c: CPRStrategy(c)),  # type: ignore[arg-type]
        ("previous_day_breakout", PreviousDayBreakoutConfig, lambda c: PreviousDayBreakoutStrategy(c)),  # type: ignore[arg-type]
        ("volume_breakout", VolumeBreakoutConfig, lambda c: VolumeBreakoutStrategy(c)),  # type: ignore[arg-type]
        ("donchian", DonchianStrategyConfig, lambda c: DonchianStrategy(c)),  # type: ignore[arg-type]
        ("darvas_box", DarvasBoxStrategyConfig, lambda c: DarvasBoxStrategy(c)),  # type: ignore[arg-type]
        ("relative_strength", RelativeStrengthConfig, lambda c: RelativeStrengthStrategy(c)),  # type: ignore[arg-type]
    ]
    for name, config_cls, builder in specs:
        register_binding(
            StrategyConfigBinding(
                strategy_name=name,
                config_cls=config_cls,
                builder=builder,
            ),
        )


def validate_filter_references(system: StrategySystemConfig) -> None:
    """Ensure filter ids referenced in config exist in the catalog / profile."""
    from app.strategy_engine.filters.catalog import FILTER_CATALOG
    from app.strategy_engine.filters.strategy_profiles import get_strategy_filter_profile

    profile = get_strategy_filter_profile(system.strategy_name)
    known = set(FILTER_CATALOG.keys()) | {spec.filter_id for spec in profile.all_specs()}
    for filter_id in (*system.filters.enable_optional, *system.filters.disable):
        if filter_id not in known:
            raise StrategyConfigValidationError(
                f"Unknown filter id '{filter_id}' for strategy '{system.strategy_name}'",
            )
    for filter_id in system.filters.param_overrides:
        if filter_id not in known:
            raise StrategyConfigValidationError(
                f"Unknown filter id '{filter_id}' in param_overrides "
                f"for strategy '{system.strategy_name}'",
            )


def materialize_strategy(system: StrategySystemConfig) -> BaseStrategy:
    """Validate system config and build a concrete strategy instance."""
    ensure_default_bindings()
    binding = get_binding(system.strategy_name)
    validate_filter_references(system)
    return binding.build_strategy(system)


def materialize_native_config(system: StrategySystemConfig) -> BaseModel:
    ensure_default_bindings()
    binding = get_binding(system.strategy_name)
    validate_filter_references(system)
    return binding.build_native_config(system)


def default_system_config(strategy_name: str, **overrides: Any) -> StrategySystemConfig:
    """Build a validated default system config for ``strategy_name``."""
    ensure_default_bindings()
    binding = get_binding(strategy_name)
    native = binding.config_cls()
    dump = native.model_dump()
    # Split native defaults into sections for a clean document shape
    parameters = {
        key: value
        for key, value in dump.items()
        if key
        not in {
            "strategy_name",
            "enable_filter_pipeline",
            "filter_enable_optional",
            "filter_disable",
            "filter_param_overrides",
            "atr_stop_multiplier",
            "trailing_atr_multiplier",
            "risk_reward_1",
            "risk_reward_2",
            "holding_period_min",
            "holding_period_max",
            "holding_period_default",
            "adx_threshold",
            "relative_volume_threshold",
        }
    }
    thresholds: dict[str, Any] = {}
    if "adx_threshold" in dump:
        thresholds["adx_threshold"] = dump["adx_threshold"]
    if "relative_volume_threshold" in dump:
        thresholds["relative_volume_min"] = dump["relative_volume_threshold"]

    risk: dict[str, Any] = {}
    for key in (
        "atr_stop_multiplier",
        "trailing_atr_multiplier",
        "risk_reward_1",
        "risk_reward_2",
    ):
        if key in dump:
            risk[key] = dump[key]

    position: dict[str, Any] = {}
    for key in (
        "holding_period_min",
        "holding_period_max",
        "holding_period_default",
    ):
        if key in dump:
            position[key] = dump[key]

    payload = {
        "strategy_name": strategy_name,
        "enabled": True,
        "parameters": parameters,
        "filters": {
            "enable_pipeline": bool(dump.get("enable_filter_pipeline", False)),
            "enable_optional": list(dump.get("filter_enable_optional") or ()),
            "disable": list(dump.get("filter_disable") or ()),
        },
        "thresholds": thresholds,
        "risk": risk,
        "position": position,
    }
    payload.update(overrides)
    return StrategySystemConfig.model_validate(payload)
