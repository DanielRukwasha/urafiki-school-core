"""Institution: the tenant registry.

One row per client school ("école"). This table IS the multi-tenant
registry — every other business table carries a non-nullable ``ecole_id``
foreign key back to a row here (see ``app/models/tenant_scope.py``). No
school-specific data ever lives in code: everything that varies between
schools, including this row's own identity, is data.
"""

from app.extensions import db
from app.models.mixins import TimestampMixin


class Institution(db.Model, TimestampMixin):
    __tablename__ = "institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    short_code = db.Column(db.String(20), nullable=False, unique=True)
    address = db.Column(db.String(300), nullable=True)
    timezone = db.Column(db.String(64), nullable=False, default="UTC")
    contact_email = db.Column(db.String(200), nullable=True)
    contact_phone = db.Column(db.String(50), nullable=True)

    # Tenant resolution (see app/security/tenant.py) and lifecycle.
    domain = db.Column(db.String(255), nullable=False, unique=True)
    custom_domain = db.Column(db.String(255), nullable=True, unique=True)
    locale = db.Column(db.String(10), nullable=False, default="fr")
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Institution {self.short_code}>"
