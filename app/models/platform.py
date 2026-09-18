"""Platform-level models: outside the perimeter of any single tenant.

`SuperAdmin` is deliberately NOT a `User` with a special role and NOT a
`TenantScopedModel` — Urafiki staff operating the platform are structurally
distinct from school staff, are never created through a tenant's own admin
console, and their accounts must keep working even if every tenant is
suspended. Mixing them into `users` would make "is this account allowed to
see every school" a runtime role check instead of a schema-level fact.

`CalculationStrategy` is the shared catalog referenced by
`TenantConfig.calculation_strategy_key` (see `app/models/tenant_config.py`).
A school-specific calculation rule is registered here under a stable key,
never forked into per-school code — see ARCHITECTURE_MULTITENANT.md.

`TenantAccessAuditLog` records every time a super-admin reads or writes a
tenant's data outside that tenant's own audit trail (`GradeAuditLog` already
covers normal in-tenant mutations). It is tenant-scoped by the tenant being
accessed, so it is enumerable from that tenant's own audit view.
"""

from __future__ import annotations

import enum

from app.extensions import bcrypt, db
from app.models.mixins import TimestampMixin, utcnow
from app.models.tenant_scope import TenantScopedModel


class SuperAdmin(db.Model, TimestampMixin):
    __tablename__ = "super_admins"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SuperAdmin {self.email}>"


class CalculationStrategy(db.Model, TimestampMixin):
    """Catalog of named, reusable grade-calculation rules.

    A tenant selects one by `key` in its `TenantConfig`. The catalog grows
    with each client that needs a genuinely new rule; it never forks per
    school (see the absolute rule in ARCHITECTURE_MULTITENANT.md).
    """

    __tablename__ = "calculation_strategies"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.String(300), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CalculationStrategy {self.key}>"


class TenantAccessEventType(str, enum.Enum):
    SUPER_ADMIN_ACCESS = "SUPER_ADMIN_ACCESS"
    CROSS_TENANT_SESSION_REJECTED = "CROSS_TENANT_SESSION_REJECTED"


class TenantAccessAuditLog(db.Model, TenantScopedModel):
    """Immutable security trail for one tenant, for events outside the scope
    of `GradeAuditLog` (which only covers in-tenant grade mutations):

    - a super-admin reading/writing this tenant's data (`actor_super_admin_id`
      set, `event_type=SUPER_ADMIN_ACCESS`, `reason` always required);
    - a session whose account's `ecole_id` did not match the domain it was
      presented on (`actor_user_id` set, `event_type=
      CROSS_TENANT_SESSION_REJECTED`) — see `app/security/tenant.py`.
    """

    __tablename__ = "tenant_access_audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.Enum(TenantAccessEventType), nullable=False)
    actor_super_admin_id = db.Column(
        db.Integer, db.ForeignKey("super_admins.id"), nullable=True, index=True
    )
    actor_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    reason = db.Column(db.String(500), nullable=False)
    resource = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    super_admin = db.relationship("SuperAdmin")
    user = db.relationship("User")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TenantAccessAuditLog ecole={self.ecole_id} {self.event_type}>"
