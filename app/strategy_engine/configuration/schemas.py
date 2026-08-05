"""Unified strategy configuration schemas (JSON/YAML friendly)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FilterConfiguration(BaseModel):
    """Filter pipeline knobs exposed by every strategy config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enable_pipeline: bool = False
    enable_optional: tuple[str, ...] = ()
    disable: tuple[str, ...] = ()
    param_overrides: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("enable_optional", "disable", mode="before")
    @classmethod
    def coerce_tuple(cls, value: object) -> object:
        if value is None:
            return ()
        if isinstance(value, list):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return value


class ThresholdConfiguration(BaseModel):
    """Named thresholds (ADX, volume, confidence, etc.)."""

    model_config = ConfigDict(frozen=True, extra="allow")

    adx_threshold: float | None = Field(default=None, ge=0.0)
    relative_volume_min: float | None = Field(default=None, gt=0.0)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    min_risk_reward: float | None = Field(default=None, gt=0.0)
    max_gap_pct: float | None = Field(default=None, ge=0.0)
    min_volume: float | None = Field(default=None, ge=0.0)


class RiskConfiguration(BaseModel):
    """Risk settings shared across strategies."""

    model_config = ConfigDict(frozen=True, extra="allow")

    atr_stop_multiplier: float | None = Field(default=None, gt=0.0)
    trailing_atr_multiplier: float | None = Field(default=None, gt=0.0)
    risk_reward_1: float | None = Field(default=None, gt=0.0)
    risk_reward_2: float | None = Field(default=None, gt=0.0)
    stop_pct: float | None = Field(default=None, gt=0.0, lt=1.0)
    max_drawdown_pct: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def validate_rr_order(self) -> RiskConfiguration:
        if (
            self.risk_reward_1 is not None
            and self.risk_reward_2 is not None
            and self.risk_reward_2 < self.risk_reward_1
        ):
            raise ValueError("risk_reward_2 must be >= risk_reward_1")
        return self


class PositionConfiguration(BaseModel):
    """Position sizing / holding settings."""

    model_config = ConfigDict(frozen=True, extra="allow")

    holding_period_min: int | None = Field(default=None, ge=1)
    holding_period_max: int | None = Field(default=None, ge=1)
    holding_period_default: int | None = Field(default=None, ge=1)
    max_position_pct: float | None = Field(default=None, gt=0.0, le=100.0)
    min_quantity: float | None = Field(default=None, ge=0.0)
    min_notional: float | None = Field(default=None, ge=0.0)
    max_exposure_pct: float | None = Field(default=None, gt=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_holding_window(self) -> PositionConfiguration:
        lo, hi, default = (
            self.holding_period_min,
            self.holding_period_max,
            self.holding_period_default,
        )
        if lo is not None and hi is not None and lo > hi:
            raise ValueError("holding_period_min must be <= holding_period_max")
        if default is not None and lo is not None and default < lo:
            raise ValueError("holding_period_default must be >= holding_period_min")
        if default is not None and hi is not None and default > hi:
            raise ValueError("holding_period_default must be <= holding_period_max")
        return self


class StrategySystemConfig(BaseModel):
    """Canonical per-strategy configuration document.

    Sections
    --------
    - parameters: strategy-specific knobs (columns, lookbacks, symbols, …)
    - filters: filter pipeline enable/optional/disable/overrides
    - thresholds: indicator / signal thresholds
    - risk: stop / RR / drawdown
    - position: holding / size / exposure
    - enabled: master switch (disabled strategies must not be registered/run)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str = Field(..., min_length=1, max_length=128)
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    filters: FilterConfiguration = Field(default_factory=FilterConfiguration)
    thresholds: ThresholdConfiguration = Field(default_factory=ThresholdConfiguration)
    risk: RiskConfiguration = Field(default_factory=RiskConfiguration)
    position: PositionConfiguration = Field(default_factory=PositionConfiguration)

    @field_validator("strategy_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("strategy_name must not be blank")
        return cleaned

    def flattened_native_payload(self) -> dict[str, Any]:
        """Merge sections into a flat dict for native strategy Config models."""
        payload: dict[str, Any] = {"strategy_name": self.strategy_name}
        payload.update(dict(self.parameters))

        # Thresholds (only set keys)
        for key, value in self.thresholds.model_dump(exclude_none=True).items():
            payload[key] = value
            # Common aliases onto native config field names
            if key == "relative_volume_min":
                payload.setdefault("relative_volume_threshold", value)
            if key == "min_risk_reward":
                payload.setdefault("risk_reward_1", value)

        for key, value in self.risk.model_dump(exclude_none=True).items():
            payload[key] = value

        for key, value in self.position.model_dump(exclude_none=True).items():
            payload[key] = value

        # Filter pipeline knobs (A4X.6)
        payload["enable_filter_pipeline"] = self.filters.enable_pipeline
        payload["filter_enable_optional"] = tuple(self.filters.enable_optional)
        payload["filter_disable"] = tuple(self.filters.disable)
        if self.filters.param_overrides:
            payload["filter_param_overrides"] = dict(self.filters.param_overrides)

        return payload

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize for export / docs."""
        return self.model_dump(mode="json")


class StrategyConfigBundle(BaseModel):
    """Multi-strategy configuration document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategies: tuple[StrategySystemConfig, ...] = Field(..., min_length=1)

    @model_validator(mode="after")
    def unique_names(self) -> StrategyConfigBundle:
        names = [item.strategy_name for item in self.strategies]
        if len(names) != len(set(names)):
            raise ValueError("strategy_name values must be unique within a bundle")
        return self
