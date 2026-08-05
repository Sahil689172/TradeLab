"""Load / save strategy configuration from JSON or YAML."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.strategy_engine.configuration.exceptions import (
    StrategyConfigLoadError,
    StrategyConfigValidationError,
)
from app.strategy_engine.configuration.registry import (
    default_system_config,
    materialize_native_config,
    materialize_strategy,
    validate_filter_references,
)
from app.strategy_engine.configuration.schemas import (
    StrategyConfigBundle,
    StrategySystemConfig,
)
from app.strategy_engine.base import BaseStrategy


def _parse_text(text: str, *, suffix: str) -> Any:
    ext = suffix.lower().lstrip(".")
    if ext in {"json"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise StrategyConfigLoadError(f"Invalid JSON: {exc}") from exc
    if ext in {"yaml", "yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise StrategyConfigLoadError(
                "PyYAML is required to load YAML configs. "
                "Install with: pip install pyyaml",
            ) from exc
        try:
            return yaml.safe_load(text)
        except Exception as exc:  # noqa: BLE001 — surface YAML errors uniformly
            raise StrategyConfigLoadError(f"Invalid YAML: {exc}") from exc
    raise StrategyConfigLoadError(
        f"Unsupported config format '.{ext}' (use .json, .yaml, or .yml)",
    )


def _coerce_system_config(payload: Any) -> StrategySystemConfig:
    if not isinstance(payload, dict):
        raise StrategyConfigValidationError(
            "Strategy config root must be a mapping/object",
        )
    # Allow either a single strategy doc or {"strategies":[...]} with one entry
    if "strategies" in payload and "strategy_name" not in payload:
        bundle = StrategyConfigBundle.model_validate(payload)
        if len(bundle.strategies) != 1:
            raise StrategyConfigValidationError(
                "Expected a single strategy config; found a multi-strategy bundle. "
                "Use load_strategy_config_bundle() instead.",
            )
        return bundle.strategies[0]
    try:
        return StrategySystemConfig.model_validate(payload)
    except ValidationError as exc:
        raise StrategyConfigValidationError(str(exc)) from exc


def load_strategy_config(path: str | Path) -> StrategySystemConfig:
    """Load and validate one strategy configuration from JSON/YAML."""
    file_path = Path(path)
    if not file_path.is_file():
        raise StrategyConfigLoadError(f"Config file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8")
    payload = _parse_text(text, suffix=file_path.suffix)
    config = _coerce_system_config(payload)
    validate_filter_references(config)
    # Also ensure native config validates
    materialize_native_config(config)
    return config


def load_strategy_config_bundle(path: str | Path) -> StrategyConfigBundle:
    """Load a multi-strategy JSON/YAML bundle."""
    file_path = Path(path)
    if not file_path.is_file():
        raise StrategyConfigLoadError(f"Config file not found: {file_path}")
    text = file_path.read_text(encoding="utf-8")
    payload = _parse_text(text, suffix=file_path.suffix)
    if not isinstance(payload, dict):
        raise StrategyConfigValidationError("Bundle root must be a mapping/object")
    if "strategies" not in payload:
        # Treat a single strategy doc as a one-item bundle
        single = _coerce_system_config(payload)
        bundle = StrategyConfigBundle(strategies=(single,))
    else:
        try:
            bundle = StrategyConfigBundle.model_validate(payload)
        except ValidationError as exc:
            raise StrategyConfigValidationError(str(exc)) from exc
    for item in bundle.strategies:
        validate_filter_references(item)
        if item.enabled:
            materialize_native_config(item)
    return bundle


def load_strategy_config_dict(payload: dict[str, Any]) -> StrategySystemConfig:
    """Validate an in-memory configuration mapping."""
    config = _coerce_system_config(payload)
    validate_filter_references(config)
    materialize_native_config(config)
    return config


def save_strategy_config(
    config: StrategySystemConfig,
    path: str | Path,
    *,
    fmt: str | None = None,
) -> Path:
    """Write a strategy config to JSON or YAML."""
    file_path = Path(path)
    format_name = (fmt or file_path.suffix.lstrip(".") or "json").lower()
    payload = config.to_public_dict()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        file_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return file_path
    if format_name in {"yaml", "yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise StrategyConfigLoadError(
                "PyYAML is required to save YAML configs. "
                "Install with: pip install pyyaml",
            ) from exc
        file_path.write_text(
            yaml.safe_dump(payload, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        return file_path
    raise StrategyConfigLoadError(f"Unsupported save format '{format_name}'")


def build_strategy_from_config(path: str | Path) -> BaseStrategy:
    """Load config file and construct the corresponding strategy instance."""
    config = load_strategy_config(path)
    return materialize_strategy(config)


def build_strategy_from_dict(payload: dict[str, Any]) -> BaseStrategy:
    config = load_strategy_config_dict(payload)
    return materialize_strategy(config)


def export_default_config(
    strategy_name: str,
    path: str | Path | None = None,
    *,
    fmt: str = "json",
) -> StrategySystemConfig:
    """Export a default system config document for ``strategy_name``."""
    config = default_system_config(strategy_name)
    if path is not None:
        save_strategy_config(config, path, fmt=fmt)
    return config
