"""Verify that a disabled strategy config refuses to materialize (Phase A4X.7)."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.strategy_engine.configuration import (
    StrategyConfigValidationError,
    list_bound_strategies,
    load_strategy_config_dict,
    materialize_strategy,
)


def main() -> int:
    print("bound_strategies", len(list_bound_strategies()))

    config = load_strategy_config_dict({"strategy_name": "ema_trend", "enabled": False})
    try:
        materialize_strategy(config)
    except StrategyConfigValidationError as exc:
        print("OK_DISABLED", str(exc)[:60])
        return 0

    print("FAIL: disabled strategy was materialized")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
