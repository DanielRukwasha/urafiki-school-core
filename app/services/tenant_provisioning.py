"""Provision and export a tenant end to end, with no developer intervention.

Runs outside any HTTP request (CLI context), so there is no
`g.current_ecole_id` to default from — every row created here sets
`ecole_id` explicitly. This is the only place in the codebase where that is
expected and correct.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date

from app.extensions import db
from app.models.academic import AcademicYear
from app.models.institution import Institution
from app.models.platform import CalculationStrategy
from app.models.tenant_config import TenantConfig
from app.models.tenant_scope import TenantScopedModel
from app.models.user import RoleEnum, User

STANDARD_STRATEGY_KEY = "STANDARD"
STANDARD_STRATEGY_DESCRIPTION = (
    "Moyenne pondérée par coefficient et par période, seuil de passage "
    "unique — comportement du moteur de calcul tel que livré en P2."
)


class TenantProvisioningError(ValueError):
    """Raised when provisioning input is invalid (duplicate domain, etc.)."""


@dataclass(frozen=True)
class ProvisionResult:
    institution: Institution
    direction_user: User
    one_time_password: str
    academic_year: AcademicYear


def _ensure_standard_strategy() -> CalculationStrategy:
    strategy = CalculationStrategy.query.filter_by(key=STANDARD_STRATEGY_KEY).first()
    if strategy is None:
        strategy = CalculationStrategy(
            key=STANDARD_STRATEGY_KEY, description=STANDARD_STRATEGY_DESCRIPTION
        )
        db.session.add(strategy)
        db.session.flush()
    return strategy


def provision_tenant(
    *,
    name: str,
    short_code: str,
    domain: str,
    direction_email: str,
    direction_first_name: str,
    direction_last_name: str,
    academic_year_label: str,
    academic_year_start: date,
    academic_year_end: date,
    timezone: str = "UTC",
    locale: str = "fr",
    contact_email: str | None = None,
) -> ProvisionResult:
    if Institution.query.filter_by(domain=domain).first() is not None:
        raise TenantProvisioningError(f"domain already in use: {domain}")
    if Institution.query.filter_by(short_code=short_code).first() is not None:
        raise TenantProvisioningError(f"short_code already in use: {short_code}")

    institution = Institution(
        name=name,
        short_code=short_code,
        domain=domain,
        timezone=timezone,
        locale=locale,
        contact_email=contact_email,
        is_active=True,
    )
    db.session.add(institution)
    db.session.flush()  # assign institution.id

    strategy = _ensure_standard_strategy()

    db.session.add(
        TenantConfig(
            ecole_id=institution.id,
            calculation_strategy_key=strategy.key,
            percentage_decimal_places=2,
            mentions=[],
            eliminatory_course_codes=[],
            max_allowed_failures=None,
            report_signatures=[],
            feature_flags={},
        )
    )

    academic_year = AcademicYear(
        ecole_id=institution.id,
        label=academic_year_label,
        start_date=academic_year_start,
        end_date=academic_year_end,
        is_current=True,
    )
    db.session.add(academic_year)

    one_time_password = secrets.token_urlsafe(12)
    direction_user = User(
        ecole_id=institution.id,
        email=direction_email.lower().strip(),
        first_name=direction_first_name,
        last_name=direction_last_name,
        role=RoleEnum.DIRECTION,
        is_active_account=True,
    )
    direction_user.set_password(one_time_password)
    db.session.add(direction_user)

    db.session.commit()

    return ProvisionResult(
        institution=institution,
        direction_user=direction_user,
        one_time_password=one_time_password,
        academic_year=academic_year,
    )


def export_tenant(*, domain: str) -> dict[str, list[dict]]:
    """Full, portable export of one tenant's data, keyed by table name.

    Every `TenantScopedModel` subclass is included automatically — a new
    tenant-scoped model needs no change here to be covered by export.
    """
    institution = Institution.query.filter_by(domain=domain).first()
    if institution is None:
        raise TenantProvisioningError(f"no tenant for domain: {domain}")

    export: dict[str, list[dict]] = {
        "institutions": [_row_to_dict(institution)],
    }

    seen_tables: set[str] = set()
    for model_cls in _seen_model_classes():
        table_name = model_cls.__tablename__
        if table_name in seen_tables:
            continue
        seen_tables.add(table_name)
        rows = (
            model_cls.query.filter_by(ecole_id=institution.id)
            .execution_options(skip_tenant_filter=True)
            .all()
        )
        export[table_name] = [_row_to_dict(row) for row in rows]

    return export


def _seen_model_classes() -> list[type]:
    def _walk(cls: type) -> list[type]:
        result = []
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "__tablename__"):
                result.append(subclass)
            result.extend(_walk(subclass))
        return result

    return _walk(TenantScopedModel)


def _row_to_dict(row) -> dict:
    return {
        column.name: getattr(row, column.name) for column in row.__table__.columns
    }
