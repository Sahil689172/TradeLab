"""Strategy filter profile contracts (mandatory / optional / default / configurable)."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FilterRole(str, Enum):
    MANDATORY = "mandatory"
    OPTIONAL = "optional"
    DEFAULT = "default"
    CONFIGURABLE = "configurable"


class FilterSpec(BaseModel):
    """One filter slot inside a strategy profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filter_id: str = Field(..., min_length=1)
    role: FilterRole
    enabled: bool | None = Field(
        default=None,
        description="None → role default (mandatory/default/configurable on; optional off)",
    )
    priority: int = 100
    params: dict[str, Any] = Field(default_factory=dict)

    def is_enabled_by_role(self) -> bool:
        if self.enabled is not None:
            return bool(self.enabled)
        return self.role is not FilterRole.OPTIONAL


class StrategyFilterProfile(BaseModel):
    """Per-strategy filter policy — strategies declare slots; logic stays untouched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_name: str
    mandatory: tuple[FilterSpec, ...] = ()
    optional: tuple[FilterSpec, ...] = ()
    default: tuple[FilterSpec, ...] = ()
    configurable: tuple[FilterSpec, ...] = ()
    description: str = ""

    def all_specs(self) -> list[FilterSpec]:
        return [
            *self.mandatory,
            *self.default,
            *self.configurable,
            *self.optional,
        ]

    def resolve(
        self,
        *,
        enable_optional: set[str] | None = None,
        disable: set[str] | None = None,
        param_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list[FilterSpec]:
        """Return enabled specs in priority order (mandatory cannot be disabled)."""
        enable_optional = enable_optional or set()
        disable = disable or set()
        param_overrides = param_overrides or {}
        resolved: list[FilterSpec] = []

        for spec in self.all_specs():
            enabled = spec.is_enabled_by_role()
            if spec.role is FilterRole.OPTIONAL and spec.filter_id in enable_optional:
                enabled = True
            if spec.role is not FilterRole.MANDATORY and spec.filter_id in disable:
                enabled = False
            if spec.role is FilterRole.MANDATORY:
                enabled = True

            params = dict(spec.params)
            if spec.filter_id in param_overrides:
                params.update(param_overrides[spec.filter_id])

            resolved.append(
                spec.model_copy(
                    update={"enabled": enabled, "params": params},
                ),
            )

        active = [item for item in resolved if item.enabled]
        return sorted(active, key=lambda item: (item.priority, item.filter_id))
