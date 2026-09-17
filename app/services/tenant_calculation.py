"""Resolves a tenant's calculation configuration before any grade math runs.

No silent defaults: an incomplete `TenantConfig`, or a `calculation_strategy_key`
with no registered implementation, raises immediately — the calculation
engine never quietly assumes a value the school's configuration didn't
actually confirm.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from app.models.tenant_config import TenantConfig
from app.services.calculation_strategies import (
    UnknownCalculationStrategyError,
    get_strategy,
)


class IncompleteTenantConfigError(RuntimeError):
    """Raised when a tenant's configuration is missing or incomplete."""


@dataclass(frozen=True)
class ResolvedTenantCalculation:
    ecole_id: int
    strategy_key: str
    strategy: ModuleType
    percentage_decimal_places: int


def resolve_tenant_calculation(ecole_id: int) -> ResolvedTenantCalculation:
    config = (
        TenantConfig.query.filter_by(ecole_id=ecole_id)
        .execution_options(skip_tenant_filter=True)
        .first()
    )
    if config is None:
        raise IncompleteTenantConfigError(
            f"ecole_id={ecole_id}: no TenantConfig row — this tenant was not "
            "provisioned through provision_tenant()/flask tenant create."
        )
    if not config.calculation_strategy_key:
        raise IncompleteTenantConfigError(
            f"ecole_id={ecole_id}: calculation_strategy_key is not set."
        )
    if config.percentage_decimal_places is None:
        raise IncompleteTenantConfigError(
            f"ecole_id={ecole_id}: percentage_decimal_places is not set."
        )

    try:
        strategy = get_strategy(config.calculation_strategy_key)
    except UnknownCalculationStrategyError as exc:
        raise IncompleteTenantConfigError(
            f"ecole_id={ecole_id}: calculation_strategy_key "
            f"{config.calculation_strategy_key!r} has no registered implementation."
        ) from exc

    return ResolvedTenantCalculation(
        ecole_id=ecole_id,
        strategy_key=config.calculation_strategy_key,
        strategy=strategy,
        percentage_decimal_places=config.percentage_decimal_places,
    )
