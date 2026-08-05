"""Unit tests for Phase A4X.7 Strategy Configuration System."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.strategies.ema_trend import EMATrendStrategy
from app.strategy_engine.configuration import (
    StrategyConfigLoadError,
    StrategyConfigValidationError,
    StrategySystemConfig,
    build_strategy_from_dict,
    default_system_config,
    export_default_config,
    list_bound_strategies,
    load_strategy_config,
    load_strategy_config_bundle,
    load_strategy_config_dict,
    materialize_native_config,
    materialize_strategy,
    save_strategy_config,
)
from app.strategy_engine.configuration.registry import ensure_default_bindings


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_JSON = ROOT / "backend" / "data" / "configs" / "ema_trend.example.json"
EXAMPLE_YAML = ROOT / "backend" / "data" / "configs" / "opening_range_breakout.example.yaml"


def test_all_twelve_strategies_are_bound() -> None:
    ensure_default_bindings()
    names = set(list_bound_strategies())
    assert len(names) == 12
    assert "ema_trend" in names
    assert "opening_range_breakout" in names


def test_system_config_exposes_required_sections() -> None:
    cfg = default_system_config("ema_trend")
    assert cfg.strategy_name == "ema_trend"
    assert cfg.enabled is True
    assert isinstance(cfg.parameters, dict)
    assert cfg.filters is not None
    assert cfg.thresholds is not None
    assert cfg.risk is not None
    assert cfg.position is not None


def test_load_json_example() -> None:
    cfg = load_strategy_config(EXAMPLE_JSON)
    assert cfg.strategy_name == "ema_trend"
    assert cfg.enabled is True
    assert cfg.filters.enable_pipeline is True
    assert "trending_market" in cfg.filters.enable_optional
    assert cfg.parameters["symbol"] == "RELIANCE"
    assert cfg.risk.atr_stop_multiplier == pytest.approx(2.0)
    assert cfg.position.holding_period_default == 10

    native = materialize_native_config(cfg)
    assert native.strategy_name == "ema_trend"
    assert native.symbol == "RELIANCE"
    assert native.enable_filter_pipeline is True
    assert native.adx_threshold == pytest.approx(25.0)

    strategy = materialize_strategy(cfg)
    assert isinstance(strategy, EMATrendStrategy)
    assert strategy.filter_pipeline_enabled is True


def test_load_yaml_example() -> None:
    pytest.importorskip("yaml")
    cfg = load_strategy_config(EXAMPLE_YAML)
    assert cfg.strategy_name == "opening_range_breakout"
    assert cfg.filters.enable_pipeline is True
    assert cfg.thresholds.relative_volume_min == pytest.approx(1.5)
    strategy = materialize_strategy(cfg)
    assert strategy.name == "opening_range_breakout"


def test_enable_disable() -> None:
    payload = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    payload["enabled"] = False
    cfg = load_strategy_config_dict(payload)
    assert cfg.enabled is False
    with pytest.raises(StrategyConfigValidationError, match="disabled"):
        materialize_strategy(cfg)


def test_validation_rejects_bad_risk_rr() -> None:
    from pydantic import ValidationError

    with pytest.raises((StrategyConfigValidationError, ValidationError)):
        StrategySystemConfig.model_validate(
            {
                "strategy_name": "ema_trend",
                "risk": {"risk_reward_1": 3.0, "risk_reward_2": 1.0},
            },
        )


def test_validation_rejects_bad_holding_window() -> None:
    from pydantic import ValidationError

    with pytest.raises((StrategyConfigValidationError, ValidationError)):
        StrategySystemConfig.model_validate(
            {
                "strategy_name": "ema_trend",
                "position": {
                    "holding_period_min": 20,
                    "holding_period_max": 5,
                },
            },
        )


def test_validation_rejects_unknown_filter_id() -> None:
    payload = {
        "strategy_name": "ema_trend",
        "filters": {"enable_optional": ["not_a_real_filter"]},
    }
    with pytest.raises(StrategyConfigValidationError, match="Unknown filter"):
        load_strategy_config_dict(payload)


def test_save_and_reload_json(tmp_path: Path) -> None:
    cfg = default_system_config("vwap", parameters={"symbol": "TCS"})
    path = tmp_path / "vwap.json"
    save_strategy_config(cfg, path)
    reloaded = load_strategy_config(path)
    assert reloaded.parameters["symbol"] == "TCS"
    assert reloaded.strategy_name == "vwap"


def test_save_and_reload_yaml(tmp_path: Path) -> None:
    pytest.importorskip("yaml")
    cfg = default_system_config("momentum")
    path = tmp_path / "momentum.yaml"
    save_strategy_config(cfg, path, fmt="yaml")
    reloaded = load_strategy_config(path)
    assert reloaded.strategy_name == "momentum"


def test_bundle_load(tmp_path: Path) -> None:
    bundle = {
        "strategies": [
            default_system_config("ema_trend").to_public_dict(),
            default_system_config("vwap").to_public_dict(),
        ],
    }
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    loaded = load_strategy_config_bundle(path)
    assert len(loaded.strategies) == 2
    assert {s.strategy_name for s in loaded.strategies} == {"ema_trend", "vwap"}


def test_build_strategy_from_dict() -> None:
    strategy = build_strategy_from_dict(
        {
            "strategy_name": "ema_trend",
            "enabled": True,
            "parameters": {"symbol": "INFY"},
            "filters": {"enable_pipeline": False},
            "risk": {"atr_stop_multiplier": 1.5},
        },
    )
    assert strategy.name == "ema_trend"
    assert strategy.active_symbol == "INFY"


def test_export_default_config(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    cfg = export_default_config("donchian", path)
    assert path.is_file()
    assert cfg.strategy_name == "donchian"


def test_missing_file_raises() -> None:
    with pytest.raises(StrategyConfigLoadError, match="not found"):
        load_strategy_config("does_not_exist.json")
