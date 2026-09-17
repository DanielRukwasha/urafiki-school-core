"""Registry of named calculation strategies.

A tenant selects one by key (`TenantConfig.calculation_strategy_key`),
validated both against the database catalog (`CalculationStrategy` — so it
shows up in admin tooling and API responses) and against this in-code
registry (so an unimplemented key fails loudly instead of silently
behaving like some other strategy). The catalog grows with each school that
needs a genuinely new rule; it never forks into per-school code — see the
absolute rule in ARCHITECTURE_MULTITENANT.md.
"""

from __future__ import annotations

from types import ModuleType

from app.services import grade_calculation_engine

STANDARD_STRATEGY_KEY = "STANDARD"

STRATEGY_REGISTRY: dict[str, ModuleType] = {
    STANDARD_STRATEGY_KEY: grade_calculation_engine,
}


class UnknownCalculationStrategyError(ValueError):
    """Raised when a tenant's configured strategy key has no implementation."""


def get_strategy(key: str) -> ModuleType:
    try:
        return STRATEGY_REGISTRY[key]
    except KeyError as exc:
        raise UnknownCalculationStrategyError(key) from exc
